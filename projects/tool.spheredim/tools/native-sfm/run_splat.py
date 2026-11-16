#!/usr/bin/env python3
"""Verify a prepared native ERP splat command and run it with a storage watchdog."""
import argparse
import json
import os
from pathlib import Path
import queue
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import prepare_splat as prep


def verify(path):
    path=path.resolve(strict=True);m=json.loads(path.read_text());root=path.parent;source=Path(m['dataset']).resolve(strict=True);model=Path(m['model']).resolve(strict=True);command=m['command'];binary=Path(command[0]).resolve(strict=True)
    if prep.digest(binary)!=m['binary_sha256'] or prep.digest(source/'manifest.json')!=m['source_manifest_sha256'] or prep.digest(root/'seed.ply')!=m['seed_sha256']:raise ValueError('Binary, input manifest or seed hash mismatch')
    for name,h in m['model_hashes'].items():
        if prep.digest(model/name)!=h:raise ValueError(f'Model hash mismatch: {name}')
    if command[1:3]!=['train','360-camera'] or (len(command)-3)%2:raise ValueError('Unexpected command shape')
    flags={}
    for i in range(3,len(command),2):
        key,value=command[i:i+2]
        if not key.startswith('--') or key in flags:raise ValueError('Duplicate or invalid command option')
        flags[key]=value
    try:iterations=int(flags['--num-iterations']);save_every=int(flags['--steps-per-save'])
    except (KeyError,ValueError):raise ValueError('Invalid training schedule')
    prep.validate_schedule(iterations,save_every)
    if flags['--num-iterations']!=str(iterations) or flags['--steps-per-save']!=str(save_every):raise ValueError('Noncanonical training schedule')
    required={'--data':str(root),'--seed-pointcloud':'seed.ply','--num-iterations':str(iterations),'--steps-per-save':str(save_every),'--save-full-checkpoint':'1','--disable-viewer':'1','--cap-max':'300000','--min-init-fraction':'0','--sampling-seed':'42','--load-masks':'1','--apply-loss-for-mask':'0','--flip-mask':'0','--mask-boundary-offset':'0','--warp-spherical-to-pinhole':'0','--warp-to-pinhole':'0','--eval-mode':'filename','--eval-lpips':'0','--save-eval-images':'1','--auto-scale-poses':'0','--orientation-method':'none','--center-method':'none','--scene-center':'none','--calib-correction':'off','--use-calib-warp':'0','--perceptual-loss':'ssim','--eval-align':'0'}
    if '--log-performance' in flags:required['--log-performance']='1'
    if '--packed' in flags:required['--packed']='0'
    if '--use-bilateral-grid' in flags or '--use-ppisp' in flags:required.update({'--use-bilateral-grid':'0','--use-ppisp':'0'})
    if set(flags)!=set(required)|{'--output-dir-prefix','--output-dir-name'} or any(flags.get(k)!=v for k,v in required.items()):raise ValueError('Command differs from reviewed ERP training settings')
    prefix=Path(flags['--output-dir-prefix']).resolve(strict=True);name=flags['--output-dir-name']
    if not name or Path(name).name!=name:raise ValueError('Invalid run name')
    output=prefix/name
    if output.exists() or output.is_symlink():raise FileExistsError(output)
    source_manifest=json.loads((source/'manifest.json').read_text());byframe={x['source_frame']:x for x in source_manifest['frames']};records=m['frames'];cameras,poses,points=prep.read_model(model)
    if len(records)!=m['camera_count'] or len(records)!=len(poses) or len({r['name'] for r in records})!=len(records) or len(byframe)*2!=len(records) or len(points)!=m['point_count']:raise ValueError('Invalid dataset inventory')
    lookup={n:r for n,r in poses};cam_ids={x[0] for x in cameras};seen=set();train=0;evals=[];lines=[]
    if len(cameras)!=2 or len(cam_ids)!=2:raise ValueError('Invalid camera inventory')
    for r in sorted(records,key=lambda x:x['source_name']):
        lens=r['lens'];frame=r['source_frame'];src=r['source_name'];new=r['name'];split=r['split']
        if lens not in ('cam0','cam1') or split not in ('train','eval') or src!=f'{lens}/frame_{frame:06}.png' or new!=f'{split}_{frame:06}_{lens}.png' or (frame,lens) in seen or frame not in byframe:raise ValueError('Invalid frame mapping')
        seen.add((frame,lens));f=byframe[frame]
        if r['timestamp_microseconds']!=f['timestamp_microseconds'] or r['source_packet_pts']!=f['source_packet_pts'] or src not in lookup:raise ValueError('Frame provenance mismatch')
        row=lookup[src]
        if r['colmap_image_id']!=row[0] or r['colmap_camera_id']!=row[8] or row[8] not in cam_ids:raise ValueError('Pose identity mismatch')
        for folder,key in (('images','image_sha256'),('masks','mask_sha256')):
            original=source/folder/src;linked=root/folder/new
            if linked.is_symlink() or not os.path.samefile(original,linked) or prep.digest(linked)!=f['lenses'][lens][key]:raise ValueError(f'Hardlink or hash mismatch: {linked}')
        lines.append(' '.join([str(row[0]),*[format(x,'.17g') for x in row[1:8]],str(row[8]),new])+'\n\n')
        if split=='train':train+=1
        else:evals.append(new)
    if sorted(evals)!=m['heldout_evaluation_order'] or train<2 or any({r['split'] for r in records if r['source_frame']==f}!={'train'} and {r['split'] for r in records if r['source_frame']==f}!={'eval'} for f in byframe):raise ValueError('Invalid held-out split')
    camera_text=''.join(f'{i} EQUIRECTANGULAR {w} {h} {a:.17g} {b:.17g}\n' for i,w,h,a,b in cameras)
    if (root/'sparse/0/cameras.txt').read_text()!=camera_text or (root/'sparse/0/images.txt').read_text()!=''.join(lines):raise ValueError('Prepared camera/pose data changed')
    return command,output,train,len(evals),iterations


def tree_size(path):
    if not path.exists():return 0
    return sum(p.stat().st_size for p in path.rglob('*') if p.is_file() and not p.is_symlink())


def publish(path,state):
    fd,tmp=tempfile.mkstemp(prefix='.splat-status-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as f:json.dump(state,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def complete_splat_ply(path):
    """Return a stable file signature only for a complete supported splat PLY."""
    try:
        before=path.stat()
        if not path.is_file() or path.is_symlink(): return None
        with path.open('rb') as f:
            opened=os.fstat(f.fileno())
            signature=lambda st:(st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns)
            if signature(before)!=signature(opened):return None
            header=bytearray()
            while len(header)<65536:
                line=f.readline(min(4097,65536-len(header)))
                if not line or len(line)>4096 or not line.endswith(b'\n'):return None
                header.extend(line)
                if line==b'end_header\n':break
            else:return None
            try: lines=header.decode('ascii').splitlines()
            except UnicodeDecodeError:return None
            if len(lines)<5 or lines[0]!='ply' or lines[1]!='format binary_little_endian 1.0' or lines[-1]!='end_header':return None
            vertex=None;properties=[]
            for line in lines[2:-1]:
                words=line.split()
                if not words:return None
                if words[0] in ('comment','obj_info'):continue
                if words[0]=='element' and len(words)==3 and words[1]=='vertex' and vertex is None and words[2].isdigit():vertex=int(words[2]);continue
                if words[0]=='property' and len(words)==3 and words[1]=='float' and vertex is not None and words[2] not in properties:properties.append(words[2]);continue
                return None
            if vertex is None or vertex<=0 or not {'x','y','z','opacity','scale_0','scale_1','scale_2','rot_0','rot_1','rot_2','rot_3'}.issubset(properties):return None
            if opened.st_size!=len(header)+vertex*4*len(properties):return None
            if signature(os.fstat(f.fileno()))!=signature(opened):return None
        if signature(path.stat())!=signature(opened):return None
        return signature(opened)
    except (OSError,ValueError):return None


def checkpoints(output,previous,final=False):
    observed={};ready=[]
    if output.is_dir():
        for directory in output.glob('step-*.ckpt'):
            match=re.fullmatch(r'step-(\d+)\.ckpt',directory.name);ply=directory/'splat.ply'
            if not match or directory.is_symlink():continue
            signature=complete_splat_ply(ply)
            if signature is None:continue
            observed[str(ply)]=signature
            if final or previous.get(str(ply))==signature:ready.append((int(match.group(1)),ply))
    return observed,sorted(ready)


def publish_activity(path,state,output,log,ready):
    try:activity=json.loads(path.read_text())
    except FileNotFoundError:activity={}
    if not isinstance(activity,dict):raise ValueError('Activity state must be an object')
    status={'starting':'running','running':'running','complete':'complete','error':'failed','cancelled':'failed'}[state['status']]
    training={'name':'Gaussian training','status':status,'current':state['current'],'total':state['total']}
    if state.get('error'):training['detail']=state['error']
    activity.update(stages=[training,{'name':'Image comparison','status':'pending'}],currentActivity=1 if status=='complete' else 0,logs=[{'name':'Gaussian training','file':os.path.relpath(log,path.parent)}])
    artifacts=activity.get('artifacts',{})
    if not isinstance(artifacts,dict):raise ValueError('Activity artifacts must be an object')
    artifacts['splat']=({'file':os.path.relpath(ready[-1][1],path.parent),'run':output.name,'checkpoint':ready[-1][0]} if ready else None)
    activity['artifacts']=artifacts;publish(path,activity)


def monitor(command,output,progress,log,expected,total=3000,timeout=600,limit=1024**3,reserve=35*1024**3,interval=1,activity=None):
    state={'stage':'gaussian_training','status':'starting','current':0,'total':total,'iteration':0,'camera_count':None,'camera_count_after_splitting':None,'output_dir':str(output),'log':str(log),'checkpoints':[],'error':None};start=time.monotonic();proc=None;reason=None;q=queue.Queue();observed={}
    def update():
        nonlocal observed
        observed,ready=checkpoints(output,observed,state['status']=='complete')
        state['elapsed_seconds']=round(time.monotonic()-start,2);state['output_bytes']=tree_size(output)+sum(p.stat().st_size for p in (log,progress) if p.exists());state['free_bytes']=shutil.disk_usage(output.parent).free;state['checkpoints']=[str(p.resolve()) for _,p in ready];publish(progress,state)
        if activity is not None:publish_activity(activity,state,output,log,ready)
    def reader(stream):
        try:
            for line in iter(lambda:os.read(stream.fileno(),8192),b''):q.put(line)
        finally:q.put(None)
    def stop():
        if proc and proc.poll() is None:
            os.killpg(proc.pid,signal.SIGTERM)
            try:proc.wait(timeout=5)
            except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()
    with progress.open('x') as f:json.dump(state,f)
    try:
        with log.open('xb',buffering=0) as out:
            update()
            if state['free_bytes']<reserve:raise RuntimeError('Free-space reserve violated before launch')
            proc=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=True,env=dict(os.environ,SS_LANG='en'));state.update(status='running',pid=proc.pid);thread=threading.Thread(target=reader,args=(proc.stdout,),daemon=True);thread.start();done=False;pending=''
            while True:
                until=time.monotonic()+interval
                while True:
                    try:line=q.get(timeout=max(0,until-time.monotonic()))
                    except queue.Empty:break
                    if line is None:done=True;break
                    out.write(line);pending+=line.decode('utf-8',errors='replace')
                    for camera in re.finditer(r'Cameras:\s*(\d+)\s*\((\d+) after splitting\)',pending):
                        x,y=map(int,camera.groups());state.update(camera_count=x,camera_count_after_splitting=y)
                        if (x,y)!=(expected,expected):reason=f'Camera count mismatch: expected {expected}, got {x} to {y}';break
                    if reason:break
                    for step in re.finditer(r'step\s+(\d+)/(\d+)(?=\D)',pending):
                        n,t=map(int,step.groups())
                        if t!=total or n>total:reason=f'Invalid progress {n}/{t}';break
                        state.update(current=n,iteration=n)
                    if reason:break
                    pending=pending[-256:]
                    if time.monotonic()>=until:break
                update()
                if reason is None and state['output_bytes']>limit:reason='Output size limit exceeded'
                if reason is None and state['free_bytes']<reserve:reason='Free-space reserve violated'
                if reason is None and time.monotonic()-start>timeout:reason='Training timeout exceeded'
                if reason:stop();break
                if done and proc.poll() is not None:break
            code=proc.wait();thread.join(timeout=1);proc.stdout.close();state['exit_code']=code
            if not reason and (code!=0 or state['camera_count']!=expected or state['camera_count_after_splitting']!=expected or state['current']!=total):reason=f'Incomplete trainer: exit={code}, cameras={state["camera_count"]}/{state["camera_count_after_splitting"]}, step={state["current"]}/{total}'
            if not reason and not any(step==total for step,_ in checkpoints(output,{},True)[1]):reason=f'Missing final step-{total} checkpoint splat.ply'
            state.update(status='error' if reason else 'complete',error=reason);update()
    except BaseException as exc:
        stop();state.update(status='cancelled' if isinstance(exc,KeyboardInterrupt) else 'error',error=f'{type(exc).__name__}: {exc}');update();raise
    return state


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('manifest',type=Path);p.add_argument('progress',type=Path);p.add_argument('log',type=Path);p.add_argument('--activity-state',type=Path,help='Existing or new activity JSON to update atomically');p.add_argument('--timeout',type=int,default=600,help='Maximum seconds (default 600)');a=p.parse_args()
    if not 1<=a.timeout<=86400:p.error('Timeout must be between 1 and 86400 seconds')
    if any(x.exists() or x.is_symlink() for x in (a.progress,a.log)) or not all(x.parent.is_dir() for x in (a.progress,a.log)):p.error('Progress and log must be new paths in existing directories')
    if a.activity_state is not None and (not a.activity_state.parent.is_dir() or a.activity_state.resolve() in (a.progress.resolve(),a.log.resolve(),a.manifest.resolve())):p.error('Activity state must be a distinct path in an existing directory')
    command,output,train,ev,iterations=verify(a.manifest);print(f'Verified {train} training cameras and {ev} evaluation cameras; starting bounded run',flush=True)
    state=monitor(command,output,a.progress,a.log,train,total=iterations,timeout=a.timeout,activity=a.activity_state)
    if state['status']!='complete':raise SystemExit(1)
if __name__=='__main__':main()
