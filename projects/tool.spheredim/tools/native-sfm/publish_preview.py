#!/usr/bin/env python3
"""Publish an atomic viewer snapshot from Spirula SfM progress or COLMAP output."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import sys
import time

import numpy as np

BODY_FROM_CV=np.array([[0.,0.,-1.],[1.,0.,0.],[0.,-1.,0.]])
CV_FROM_GL=np.diag([1.,-1.,-1.])


def read_exact(f,n):
    data=f.read(n)
    if len(data)!=n: raise ValueError('incomplete snapshot')
    return data


def unpack(f,fmt): return struct.unpack('<'+fmt,read_exact(f,struct.calcsize('<'+fmt)))


def match_names(path):
    with path.open('rb') as f:
        if read_exact(f,4)!=b'VKMT': raise ValueError('invalid matches header')
        version,count=unpack(f,'II')
        if version not in (2,3,4,5) or count>1000000: raise ValueError('unsupported matches version')
        names=[]
        for _ in range(count):
            n,=unpack(f,'I')
            if n>16384: raise ValueError('invalid image name')
            names.append(read_exact(f,n).decode());unpack(f,'I')
        return names


def progress_model(path,names):
    with path.open('rb') as f:
        if read_exact(f,4)!=b'VKPM': raise ValueError('invalid model header')
        version,flags,total,registered=unpack(f,'IIII'); points_total,=unpack(f,'Q')
        if version!=4 or registered>total or total!=len(names): raise ValueError('unsupported or mismatched model')
        poses={}
        for _ in range(registered):
            idx,=unpack(f,'I'); mat=np.array(unpack(f,'12f')).reshape(3,4)
            _,_,_,n=unpack(f,'IIII')
            if idx>=len(names) or n>32: raise ValueError('invalid model camera')
            unpack(f,str(n)+'d')
            if names[idx] in poses or not np.isfinite(mat).all(): raise ValueError('invalid model pose')
            mat[:,:3]=mat[:,:3]@CV_FROM_GL
            poses[names[idx]]=mat
        n,=unpack(f,'I')
        if n>points_total or n>1000000: raise ValueError('invalid point count')
        points=[]
        for _ in range(n):
            xyz=unpack(f,'3f');rgb=unpack(f,'3B')
            if not all(math.isfinite(x) for x in xyz): raise ValueError('invalid point')
            points.append((*xyz,*rgb))
        if f.read(1): raise ValueError('trailing model bytes')
        return poses,points,flags


def rotation(q):
    q=np.array(q,dtype=float);norm=np.linalg.norm(q)
    if not np.isfinite(q).all() or abs(norm-1)>1e-3: raise ValueError('invalid quaternion')
    w,x,y,z=q/norm
    return np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)],
                     [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)],
                     [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])


def colmap_model(path):
    poses={};points=[]
    with (path/'images.bin').open('rb') as f:
        count,=unpack(f,'Q')
        if count>1000000: raise ValueError('invalid image count')
        for _ in range(count):
            row=unpack(f,'i7di'); name=bytearray()
            while True:
                c=read_exact(f,1)
                if c==b'\0': break
                name+=c
                if len(name)>16384: raise ValueError('invalid name')
            name=name.decode(); R=rotation(row[1:5]); t=np.array(row[5:8]); mat=np.column_stack((R.T,-R.T@t))
            if not np.isfinite(mat).all() or name in poses: raise ValueError('invalid pose')
            poses[name]=mat
            n,=unpack(f,'Q')
            if n>10000000: raise ValueError('invalid image points')
            read_exact(f,n*24)
    with (path/'points3D.bin').open('rb') as f:
        count,=unpack(f,'Q')
        if count>10000000: raise ValueError('invalid point count')
        for _ in range(count):
            row=unpack(f,'Q3d3Bd'); n,=unpack(f,'Q')
            if n>10000000 or not all(math.isfinite(x) for x in row[1:4]): raise ValueError('invalid point')
            read_exact(f,n*8); points.append((*row[1:4],*row[4:7]))
    return poses,points,0


def build_frames(poses,dataset):
    rows={int(x['source_frame']):x for x in dataset['frames']}
    if len(rows)!=len(dataset['frames']): raise ValueError('duplicate dataset frame')
    frames=[]; align=[]
    for name,mat in poses.items():
        if not name.startswith('cam0/'): continue
        stem=Path(name).stem
        if not stem.startswith('frame_') or not stem[6:].isdigit(): raise ValueError('invalid image name')
        source=int(stem[6:]); row=rows[source]; ts=float(row['timestamp_microseconds'])/1e6
        if not math.isfinite(ts): raise ValueError('invalid timestamp')
        frames.append({'source_frame':source,'image':name,'time_seconds':ts,'world_from_camera':mat.tolist()})
        q=row.get('fused_row')
        if q:
            fused=rotation([float(q[k]) for k in ('q_w','q_x','q_y','q_z')])@BODY_FROM_CV
            align.append(mat[:,:3]@fused.T)
    frames.sort(key=lambda x:x['time_seconds'])
    if not frames or any(a['time_seconds']>=b['time_seconds'] for a,b in zip(frames,frames[1:])): raise ValueError('no ordered body poses')
    up=[0.,1.,0.];method='fallback +Y; fused alignment unavailable'
    if len(align)>=3:
        u,_,vt=np.linalg.svd(sum(align));D=np.diag([1,1,np.linalg.det(u@vt)]);model_from_fused=u@D@vt
        angles=[math.degrees(math.acos(float(np.clip((np.trace(a@model_from_fused.T)-1)/2,-1,1)))) for a in align]
        median=float(np.median(angles))
        if median <= 15:
            up=(model_from_fused@np.array([0.,0.,1.])).tolist()
            method=f'fused gravity +Z aligned to model cameras; median rotation disagreement {median:.1f} degrees'
        else:
            method=f'fallback +Y; fused/model orientation disagreement {median:.1f} degrees'
    return frames,up,method


def atomic(path,data):
    tmp=path.with_name('.'+path.name+'.tmp')
    with tmp.open('wb') as f: f.write(data);f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)



def read_status(path):
    raw=path.read_bytes()
    if len(raw)!=struct.calcsize('<4sIII6qd'): raise ValueError('incomplete status')
    magic,version,index,flags,done,total,registered,images,points,models,error=struct.unpack('<4sIII6qd',raw)
    if magic!=b'VKPS' or version!=1 or index>=12: raise ValueError('unsupported status')
    return {'stage':index,'flags':flags,'done':done,'total':total,'registered':registered,
            'images':images,'points':points,'models':models}


def status_stage(status):
    names=['Extracting','Matching','Mapping','Merging','Orienting','Finishing','Loading','Selecting pairs','Seeding','Refining','Calibrating','Initializing']
    if status is None: return {'name':'Camera pose estimation','status':'running'}
    flags=status['flags']
    if flags & 1:
        partial=bool(flags & 2)
        return {'name':'Camera pose estimation','status':'partial' if partial else 'complete',
                'detail':'Pose estimation partial' if partial else 'Pose estimation finished'}
    out={'name':names[status['stage']],'status':'running'}
    if status['total']>0 and status['done']>=0:
        out.update(current=status['done'],total=status['total'])
    return out


def coverage_details(status):
    if status is None: return []
    parts=[]
    if status['images']>0 and status['registered']>=0: parts.append(f"{status['registered']}/{status['images']} lens images registered")
    if status['points']>0: parts.append(f"{status['points']} native points")
    if status['models']>0: parts.append(f"{status['models']} model(s)")
    return ['; '.join(parts)] if parts else []


def activity_override(path, run, output):
    if path is None: return None
    path=path.resolve()
    if path.parent != run: return None
    try:
        value=json.loads(path.read_text())
        stages=value['stages']; current=value['currentActivity']
        if not isinstance(stages,list) or not stages or not isinstance(current,int) or isinstance(current,bool) or not 0<=current<len(stages): return None
        for stage in stages:
            if not isinstance(stage,dict) or not isinstance(stage.get('name'),str) or stage.get('status') not in ('running','complete','partial','pending','failed'): return None
        logs=[]
        for log in value.get('logs',[]):
            if not isinstance(log,dict) or not isinstance(log.get('name'),str) or not isinstance(log.get('file'),str): return None
            log_path=(path.parent/log['file']).resolve()
            logs.append({'name':log['name'],'file':os.path.relpath(log_path,output)})
        artifact_input=value.get('artifacts',{})
        if not isinstance(artifact_input,dict) or set(artifact_input)-{'splat','dense','mesh'}: return None
        artifacts={'splat':None,'dense':None,'mesh':None}
        for kind,descriptor in artifact_input.items():
            if descriptor is None: continue
            if not isinstance(descriptor,dict) or not isinstance(descriptor.get('file'),str) or not descriptor['file']: return None
            for field in ('file','transform','run','label','space'):
                if field in descriptor and (not isinstance(descriptor[field],str) or not descriptor[field]): return None
            if 'checkpoint' in descriptor:
                checkpoint=descriptor['checkpoint']
                if not ((isinstance(checkpoint,str) and checkpoint) or (isinstance(checkpoint,int) and not isinstance(checkpoint,bool) and checkpoint>=0)): return None
            if 'space' in descriptor and descriptor['space'] not in ('train','world'): return None
            item=dict(descriptor)
            for field in ('file','transform'):
                if field in item: item[field]=os.path.relpath((path.parent/item[field]).resolve(),output)
            artifacts[kind]=item
        return {'stages':stages,'currentActivity':current,'logs':logs,'artifacts':artifacts}
    except (OSError,ValueError,KeyError,TypeError): return None


def activity_or_status(path,run,output,native):
    if path is None:
        return {'stages':[status_stage(native)],'currentActivity':0,'logs':[],'artifacts':{'splat':None,'dense':None,'mesh':None}}
    activity=activity_override(path,run,output)
    if activity is not None: return activity
    return {'stages':[{'name':'Activity unavailable','status':'failed',
                       'detail':'Configured activity file is missing, invalid, or belongs to another run.'}],
            'currentActivity':0,'logs':[],'artifacts':{'splat':None,'dense':None,'mesh':None}}

def publish(progress,model,dataset_path,output,reference=None,activity_state=None):
    # Pin both paths to a single run before reading a movable source pointer.
    progress_input,model_input=progress,model
    output=output.resolve()
    progress=progress.resolve();model=model.resolve()
    run=model.parent.parent
    if progress.parent!=run:
        raise ValueError('progress and model must belong to the same run')
    source_id=str(run)
    dataset=json.loads(dataset_path.read_text())
    try: status=read_status(progress/'status.bin')
    except (OSError,ValueError,struct.error): status=None
    log={'name':'Reconstruction','file':os.path.relpath(run/'run.log',output)}
    activity=activity_or_status(activity_state,run,output,status)
    stages=activity['stages']
    current=activity['currentActivity']
    logs=[log]+activity['logs']
    state_path=output/'viewer-state.json'
    try: previous=json.loads(state_path.read_text())
    except (OSError,ValueError): previous={}
    if previous.get('source')!=source_id:
        # Clear the previous run before attempting to decode this run's model.
        pending={'version':1,'source':source_id,'trajectory':{},'artifacts':activity['artifacts'],
                 'stages':stages,'currentActivity':current,'logs':logs,
                 'details':['Waiting for this run’s first complete reconstruction snapshot.']+coverage_details(status)}
        atomic(state_path,(json.dumps(pending,indent=2,allow_nan=False)+'\n').encode())
    source=progress/'model.bin'
    final_ready=False
    if status and status['flags'] & 1:
        try:
            final_files=[model/'images.bin',model/'points3D.bin']
            before=[(p.stat().st_mtime_ns,p.stat().st_size) for p in final_files]
            if source.is_file() and any(t < source.stat().st_mtime_ns for t,_ in before):
                raise ValueError('final model predates native snapshot')
            poses,points,flags=colmap_model(model)
            blob=b''.join(p.read_bytes() for p in final_files)
            if before!=[(p.stat().st_mtime_ns,p.stat().st_size) for p in final_files]:
                raise ValueError('final model changed while reading')
            identity=b''; origin='final COLMAP model'; final_ready=True
        except (OSError,ValueError,struct.error):
            pass
    if not final_ready and source.is_file():
        blob=source.read_bytes(); match_file=model.parent.parent/'matches.bin'; names=match_names(match_file)
        identity=match_file.read_bytes()
        temp=output/'.model-read.tmp';atomic(temp,blob)
        try: poses,points,flags=progress_model(temp,names)
        finally: temp.unlink(missing_ok=True)
        origin='native progress model.bin'
    elif not final_ready:
        poses,points,flags=colmap_model(model);blob=(model/'images.bin').read_bytes()+(model/'points3D.bin').read_bytes();identity=b'';origin='final COLMAP model'
    frames,up,up_method=build_frames(poses,dataset)
    key=hashlib.sha256(source_id.encode()+blob+hashlib.sha256(identity).digest()+hashlib.sha256(dataset_path.read_bytes()).digest()).hexdigest()[:20]
    pose_name='poses-'+key+'.json';point_name='points-'+key+'.ply'
    pose_bytes=(json.dumps({'schema':'spheredim-viewer-poses-v1','frames':frames},allow_nan=False)+'\n').encode()
    ply=('ply\nformat ascii 1.0\nelement vertex '+str(len(points))+'\nproperty float x\nproperty float y\nproperty float z\nproperty uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n'+''.join('%g %g %g %d %d %d\n'%p for p in points)).encode()
    if not (output/pose_name).is_file(): atomic(output/pose_name,pose_bytes)
    if not (output/point_name).is_file(): atomic(output/point_name,ply)
    trajectory={'poses':pose_name,'points':point_name};artifacts=activity['artifacts']
    selected=dataset['frames']
    times=[float(row['timestamp_microseconds'])/1e6 for row in selected]
    if not times or not all(map(math.isfinite,times)): raise ValueError('invalid dataset interval')
    scope=f"{len(selected)} selected timestamps, {min(times):.2f}–{max(times):.2f} s"
    details=[f'{origin}: {len(frames)}/{len(selected)} selected body poses, {len(points)} displayed points.',
             f'Selected recording interval: {scope}.',up_method]+coverage_details(status)
    state={'version':1,'source':source_id,'trajectory':trajectory,'artifacts':artifacts,'up':up,
           'details':details,'stages':stages,'currentActivity':current,'logs':logs,'generation':key}
    if reference: state['reference']={'file':os.path.relpath(reference,output),'label':'Stabilized source panorama at source timestamp'}
    state_bytes=(json.dumps(state,indent=2,allow_nan=False)+'\n').encode()
    if progress_input.resolve()!=progress or model_input.resolve()!=model:
        raise ValueError('source changed during publication')
    if not state_path.exists() or state_path.read_bytes()!=state_bytes: atomic(state_path,state_bytes)
    # Keep a few prior complete generations for viewers fetching during a switch.
    for pattern in ('poses-*.json','points-*.ply'):
        old=sorted(output.glob(pattern),key=lambda p:p.stat().st_mtime,reverse=True)
        for p in old[8:]: p.unlink(missing_ok=True)
    return key



def refresh_activity(progress,model,output,activity_state):
    """Update activity on a same-run last-good profile if a snapshot is incomplete."""
    progress=progress.resolve();model=model.resolve();output=output.resolve()
    run=model.parent.parent
    if progress.parent!=run: return
    path=output/'viewer-state.json'
    try:
        state=json.loads(path.read_text())
        if state.get('source')!=str(run): return
        try: native=read_status(progress/'status.bin')
        except (OSError,ValueError,struct.error): native=None
        activity=activity_or_status(activity_state,run,output,native)
        state['stages']=activity['stages']
        state['currentActivity']=activity['currentActivity']
        state['artifacts']=activity['artifacts']
        state['logs']=[{'name':'Reconstruction','file':os.path.relpath(run/'run.log',output)}]+activity['logs']
        data=(json.dumps(state,indent=2,allow_nan=False)+'\n').encode()
        if path.read_bytes()!=data: atomic(path,data)
    except (OSError,ValueError,KeyError,TypeError): return

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for flag in ('progress','model','dataset-manifest','output'):p.add_argument('--'+flag,type=Path,required=True)
    p.add_argument('--reference',type=Path);p.add_argument('--activity-state',type=Path, help='Run-local JSON with stages, currentActivity, and optional logs relative to that file')
    p.add_argument('--watch',action='store_true');p.add_argument('--interval',type=float,default=2)
    a=p.parse_args()
    if a.interval<=0:p.error('interval must be positive')
    a.output.mkdir(parents=True,exist_ok=True); last=None
    while True:
        try:
            key=publish(a.progress,a.model,a.dataset_manifest,a.output,a.reference,a.activity_state)
            if key!=last:print('published',key,flush=True);last=key
        except (OSError,ValueError,KeyError,struct.error,json.JSONDecodeError) as e:
            if not a.watch:raise
            refresh_activity(a.progress,a.model,a.output,a.activity_state)
            if last is None:print('waiting for valid reconstruction:',e,file=sys.stderr,flush=True)
        if not a.watch:break
        time.sleep(a.interval)

if __name__=='__main__':main()
