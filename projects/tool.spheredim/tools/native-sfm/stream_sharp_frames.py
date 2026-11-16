#!/usr/bin/env python3
"""Consume paired original-exporter PNGs from four bounded, concurrent workers."""
import json, os, queue, re, shutil, signal, subprocess, sys, tempfile, threading, time
from pathlib import Path

REPORT_BYTES=5*1024**2

def write_json_bounded(path, value, limit=REPORT_BYTES):
    path=Path(path);data=(json.dumps(value,indent=2,allow_nan=False)+'\n').encode()
    if len(data)>limit:raise ValueError('JSON report exceeds size limit')
    name=None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent,prefix='.sharp-',delete=False) as f:
            name=f.name;f.write(data);f.flush();os.fsync(f.fileno())
        os.link(name,path)
    finally:
        if name is not None:os.unlink(name)

MODES=('lens0','lens1','mask0','mask1')
EVENT=re.compile(r'^SPHEREDIM_FRAME (\d+) (-?\d+)$')


def signal_owned_group(proc, sig):
    # On macOS a child can exit between poll and killpg; killpg may report
    # EPERM rather than ESRCH for that state. Only ignore it after waitpid
    # through poll proves that our child has exited.
    try:
        os.killpg(proc.pid,sig)
        return True
    except (ProcessLookupError,PermissionError):
        if proc.poll() is not None:return False
        raise


def stream_frames(commands, output, requested_us, *, timeout=300, cap=40*1024**2,
                  low_water=20*1024**2, lead=2, reserve=35*1024**3, interval=.05):
    """Yield one completed four-mode pair at a time; delete files after consumption.

    Polling reports observed high water; it does not prove an instantaneous cap.
    Each command must emit ordered exact requested/actual PTS events and publish
    frame_<requested microseconds, zero padded to 16>.png atomically.
    """
    output=Path(output); targets=list(requested_us)
    if set(commands)!=set(MODES) or not targets or targets!=sorted(set(targets)) or any(t<0 for t in targets) or len({max(0,t-1) for t in targets})!=len(targets):raise ValueError('Invalid worker commands or timestamps')
    if not (0<low_water<cap and lead>=1 and timeout>0 and interval>0):raise ValueError('Invalid limits')
    output.mkdir(parents=True,exist_ok=False); events=queue.Queue(); processes={};threads=[];worker_results={};paused=set(); produced={m:0 for m in MODES}; peak=0; start=time.monotonic()
    def read(mode, pipe):
        try:
            for line in iter(pipe.readline,b''):
                text=line.decode('utf-8','replace').strip(); match=EVENT.fullmatch(text)
                if match:events.put((mode,int(match[1]),int(match[2])))
                elif text.startswith('SPHEREDIM_FRAME'):events.put((mode,None,None))
                elif text.startswith('{'):
                    try:
                        result=json.loads(text)
                        if 'backend' in result:worker_results[mode]=result
                    except json.JSONDecodeError:pass
        finally:pipe.close()
    def spool_bytes():
        total=0
        for path in output.rglob('*'):
            try:
                if path.is_file():total+=path.stat().st_size
            except FileNotFoundError:
                pass  # Atomic publish can rename a temporary file during polling.
        return total
    def measure():
        nonlocal peak
        size=spool_bytes();peak=max(peak,size)
        if size>cap or shutil.disk_usage(output).free<reserve:raise RuntimeError('Observed spool cap or free-space reserve exceeded')
        return size
    def pause(mode):
        if mode not in paused and processes[mode].poll() is None:
            if signal_owned_group(processes[mode],signal.SIGSTOP):paused.add(mode)
    def resume(mode):
        if mode in paused:
            signal_owned_group(processes[mode],signal.SIGCONT)
            paused.remove(mode)
    try:
        for mode in MODES:
            env=os.environ.copy();env['SPHEREDIM_OBSERVATION_MODE']=mode;env.pop('SPHEREDIM_LENS1_INVERSE_QUAT_WXYZ',None)
            proc=subprocess.Popen(commands[mode],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,env=env,start_new_session=True);processes[mode]=proc
            thread=threading.Thread(target=read,args=(mode,proc.stdout),daemon=True);thread.start();threads.append(thread)
        for index,target in enumerate(targets):
            while True:
                while True:
                    try:mode,requested,actual=events.get_nowait()
                    except queue.Empty:break
                    i=produced[mode]
                    if requested is None or i>=len(targets) or requested!=max(0,targets[i]-1) or actual!=targets[i]:raise ValueError(f'{mode}: unknown, duplicate or mismatched timestamp {requested}/{actual}')
                    produced[mode]+=1
                files={m:output/m/f'frame_{max(0,target-1):016d}.png' for m in MODES}
                spool=measure()
                if time.monotonic()-start>timeout:raise TimeoutError('Worker timeout')
                for mode,proc in processes.items():
                    if proc.poll() not in (None,0):raise RuntimeError(f'{mode}: worker exited {proc.returncode}')
                    if produced[mode]-index>lead or (spool>low_water and produced[mode]>index+1):pause(mode)
                    else:resume(mode)
                if all(produced[m]>index and files[m].is_file() for m in MODES):break
                if all(p.poll() is not None for p in processes.values()):raise RuntimeError('Workers ended before complete pair')
                time.sleep(interval)
            # Consumer performs image decoding, mask rotation and scoring while
            # the generator is suspended; keep no producer running unchecked.
            for mode in MODES:pause(mode)
            yield target,files,{'observed_peak_spool_bytes':peak,'elapsed_seconds':time.monotonic()-start}
            for path in files.values():path.unlink()
            for mode in list(paused):resume(mode)
        for mode in list(paused):resume(mode)
        while any(proc.poll() is None for proc in processes.values()):
            measure()
            if time.monotonic()-start>timeout:raise TimeoutError('Worker timeout')
            time.sleep(interval)
        measure()  # Catch bytes written immediately before the final exit.
        for mode,proc in processes.items():
            if proc.returncode:raise RuntimeError(f'{mode}: worker exited {proc.returncode}')
        for thread in threads:thread.join(timeout=3)
        if any(t.is_alive() for t in threads) or not events.empty() or any(produced[m]!=len(targets) for m in MODES):raise ValueError('Unexpected trailing or missing timestamp event')
        if set(worker_results)!=set(MODES) or any('GPU' not in str(worker_results[m].get('backend','')) for m in MODES):raise ValueError('Missing GPU backend confirmation')
        return {'observed_peak_spool_bytes':peak}
    finally:
        for mode in list(paused):resume(mode)
        for proc in processes.values():
            if proc.poll() is None:
                signal_owned_group(proc,signal.SIGTERM)
        for proc in processes.values():
            try:proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                signal_owned_group(proc,signal.SIGKILL)
                proc.wait()
        shutil.rmtree(output)


def worker_commands(source, output, indices, micros, exporter=None):
    if len(indices)!=len(micros) or indices!=sorted(set(indices)) or micros!=sorted(set(micros)):raise ValueError('Invalid ordered paired requests')
    exporter=Path(exporter or Path(__file__).with_name('export_timestamp_probes.py'))
    return {mode:[sys.executable,str(exporter),'--worker','--source',str(source),'--output',str(Path(output)/mode),'--indices',*map(str,indices),'--timestamps',*[f'{t//1000000}.{t%1000000:06d}' for t in micros],'--width','1024','--seek-early-us','1'] for mode in MODES}


def pilot(reference, output, timeout=300, *, verify_reference=True):
    """Re-run a saved sharp-frame pilot using its exact candidate windows."""
    import csv, hashlib, importlib.util
    import cv2
    import numpy as np
    from scipy.spatial.transform import Rotation
    import select_sharp_frames as sharp
    import prepare_rig as rig
    reference=Path(reference).resolve(strict=True);output=Path(output).resolve();old=json.loads(reference.read_text())
    def sha(path):
        h=hashlib.sha256()
        with Path(path).open('rb') as f:
            for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
        return h.hexdigest()
    for key in ('source','review_manifest','fused_csv'):
        if sha(old[key])!=old[key+'_sha256']:raise ValueError(f'{key} differs from reference')
    native=importlib.util.find_spec('insta360_rs._native')
    if native is None or sha(native.origin)!=old['native_extension_sha256']:raise ValueError('Native exporter differs from reference')
    review_path=Path(old['review_manifest']);review=json.loads(review_path.read_text());reviews={x['source_frame']:x for x in review['frames']}
    with open(old['fused_csv'],newline='') as f:fused={int(x['frame']):x for x in csv.DictReader(f)}
    groups=old['results'];candidates=[c for g in groups for c in g['candidates']];indices=[c['frame'] for c in candidates];micros=[c['timestamp_microseconds'] for c in candidates]
    if indices!=sorted(set(indices)) or micros!=sorted(set(micros)):raise ValueError('Reference candidates not strictly ordered')
    for c in candidates:
        if int(round(float(fused[c['frame']]['video_pts_s'])*1e6))!=c['timestamp_microseconds']:raise ValueError('Fused candidate time mismatch')
    for path,digest in old['review_mask_sha256'].items():
        if sha(path)!=digest:raise ValueError('Reviewed mask hash mismatch')
    output.mkdir(parents=True,exist_ok=False);(output/'INCOMPLETE').write_text('Selection not complete\n');spool=output/'spool';cmd=worker_commands(old['source'],spool,indices,micros);stream=stream_frames(cmd,spool,micros,timeout=timeout);results=[];peak=0;started=time.monotonic();matched=0
    try:
        for group in groups:
            prepared=[]
            for old_c in group['candidates']:
                ts,files,stats=next(stream)
                if ts!=old_c['timestamp_microseconds']:raise ValueError('Candidate timestamp mismatch')
                peak=max(peak,stats['observed_peak_spool_bytes']); row=fused[old_c['frame']]; before,after=(reviews[n] for n in old_c['mask_brackets'])
                def mask(item):
                    data=cv2.imread(str(review_path.parent/'masks'/item['mask']),cv2.IMREAD_GRAYSCALE)
                    if data is None or data.shape!=(512,1024) or not np.isin(data,[0,255]).all():raise ValueError('Invalid reviewed mask')
                    return data==255
                stable=mask(before)&mask(after);q=Rotation.from_quat([float(row[k]) for k in ('q_x','q_y','q_z','q_w')]).as_matrix();keep=rig.operator_body_keep(stable,q.T@Rotation.from_euler('z',float(row['heading_rad'])).as_matrix());images=[];masks=[]
                hashes={}
                for mode,path in files.items():
                    digest=sha(path)
                    if verify_reference and digest!=old_c['export_sha256'][mode]:raise ValueError(f'PNG hash mismatch: {old_c["frame"]} {mode}')
                    hashes[mode]=digest;matched+=1
                for lens in range(2):
                    img=cv2.imread(str(files[f'lens{lens}']),cv2.IMREAD_COLOR);support=cv2.imread(str(files[f'mask{lens}']),cv2.IMREAD_GRAYSCALE)
                    if img is None or support is None or img.shape!=(512,1024,3) or support.shape!=(512,1024) or not np.isin(support,[0,255]).all() or np.any(img[support==0]!=0):raise ValueError('Invalid decoded physical observation')
                    images.append(img);masks.append(keep&(support==255))
                prepared.append({'frame':old_c['frame'],'timestamp_microseconds':ts,'_images':images,'_masks':masks,'export_sha256':hashes,'source_packet_pts':old_c['source_packet_pts'],'mask_brackets':old_c['mask_brackets'],'lenses':[]})
            for lens in range(2):
                vals=sharp.score_window([cv2.cvtColor(c['_images'][lens],cv2.COLOR_BGR2GRAY) for c in prepared],[c['_masks'][lens] for c in prepared],0)
                for candidate,score,prior in zip(prepared,vals,group['candidates']):
                    if verify_reference and score!=prior['lenses'][lens]:raise ValueError(f'Score mismatch: {candidate["frame"]} lens {lens}')
                    candidate['lenses'].append(score)
            winner=sharp.select(group['requested_frame'],prepared)
            if verify_reference and winner['frame']!=group['selected_frame']:raise ValueError('Selection differs from reference')
            rank=sorted(prepared,key=lambda x:(min(x['lenses'][0]['score'],x['lenses'][1]['score']),-abs(x['frame']-group['requested_frame']),-x['frame']),reverse=True)
            anchor=next((c for c in prepared if c['frame']==group['requested_frame']),None)
            if anchor is None:raise ValueError('Original anchor missing from window')
            anchor_score=min(x['score'] for x in anchor['lenses']);winner_score=min(x['score'] for x in winner['lenses'])
            for c in prepared:del c['_images'];del c['_masks']
            results.append({'requested_frame':group['requested_frame'],'selected_frame':winner['frame'],'selected_timestamp_microseconds':winner['timestamp_microseconds'],'anchor_score':anchor_score,'selected_score':winner_score,'score_gain':winner_score-anchor_score,'ranked_frames':[x['frame'] for x in rank],'candidates':prepared})
        try:next(stream);raise ValueError('Unexpected extra output')
        except StopIteration as finished:peak=max(peak,finished.value['observed_peak_spool_bytes'])
    finally:stream.close()
    report={'reference':str(reference),'reference_sha256':sha(reference),'native_extension_sha256':sha(native.origin),'source_sha256':sha(old['source']),'candidates':len(candidates),'workers':4,'all_workers_reported_gpu':True,'png_hashes_recorded':matched,'matched_png_hashes':matched if verify_reference else 0,'matched_all_scores_and_winners':verify_reference,'observed_peak_spool_bytes':peak,'elapsed_seconds':time.monotonic()-started,'spool_note':'Observed polling high-water includes temporary files; not a strict instantaneous bound.','results':results}
    write_json_bounded(output/'report.json',report,limit=REPORT_BYTES-reference.stat().st_size);(output/'INCOMPLETE').unlink();return report


def main():
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('reference',type=Path);p.add_argument('output',type=Path);p.add_argument('--timeout',type=float,default=300);a=p.parse_args();print(json.dumps(pilot(a.reference,a.output,a.timeout),indent=2))
if __name__=='__main__':main()
