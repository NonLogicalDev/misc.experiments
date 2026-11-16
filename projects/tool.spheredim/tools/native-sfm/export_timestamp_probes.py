#!/usr/bin/env python3
"""Export physical-lens ERP samples by exact timestamps, checking every emitted PTS."""
import argparse
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys


def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--indices',type=int,nargs='+',required=True);p.add_argument('--timestamps',nargs='+',required=True);p.add_argument('--width',type=int,choices=(1024,2048,4096),default=2048);p.add_argument('--seek-early-us',type=int,choices=(0,1),default=0);p.add_argument('--worker',action='store_true');a=p.parse_args()
    if len(a.indices)!=len(a.timestamps) or a.indices!=sorted(set(a.indices)):raise ValueError('Indices must be unique and sorted and pair with timestamps')
    times=[Decimal(t) for t in a.timestamps];micros=[t*1000000 for t in times]
    if any(not t.is_finite() or t!=int(t) for t in micros) or micros!=sorted(set(micros)):raise ValueError('Timestamps must be unique, sorted exact microseconds')
    requested_micros=[max(0,int(t)-a.seek_early_us) for t in micros]
    if len(set(requested_micros)) != len(requested_micros): raise ValueError('Seek timestamps collide')
    if a.worker:
        import insta360_rs as ins
        c=ins.StitchConfig(backend=ins.ProcessingBackend.GPU,stabilization=ins.Stabilization.OFF,rolling_shutter=ins.RollingShutterCorrection.OFF,seam_mode=ins.SeamMode.FIXED,width=a.width,height=a.width//2)
        r=ins.start_export_frames(str(a.source),str(a.output),timestamps=[t/1000000 for t in requested_micros],config=c,format=ins.ImageFormat.PNG).wait()
        print(json.dumps({'backend':str(r.backend.selected),'outputs':[str(x) for x in r.outputs]}));return
    if a.output.exists():raise FileExistsError(a.output)
    a.output.mkdir();results={}
    for mode in ('lens0','lens1','mask0','mask1'):
        env=os.environ.copy();env['SPHEREDIM_OBSERVATION_MODE']=mode;env.pop('SPHEREDIM_LENS1_INVERSE_QUAT_WXYZ',None)
        cmd=[sys.executable,str(Path(__file__).resolve()),'--worker','--source',str(a.source),'--output',str(a.output/mode),'--indices',*map(str,a.indices),'--timestamps',*a.timestamps,'--width',str(a.width),'--seek-early-us',str(a.seek_early_us)]
        r=subprocess.run(cmd,env=env,text=True,capture_output=True)
        if r.returncode:raise RuntimeError(f'{mode} failed: {r.stderr[-4000:]}')
        result=json.loads(r.stdout.strip().splitlines()[-1]);observed=[(int(k),int(t)) for k,t in re.findall(r'SPHEREDIM_FRAME (\d+) (-?\d+)',r.stderr)]
        expected=[(requested,int(actual)) for requested,actual in zip(requested_micros,micros)]
        if observed!=expected or 'GPU' not in result['backend']:raise ValueError(f'{mode}: emitted PTS or backend mismatch: observed={observed}, expected={expected}, backend={result["backend"]}')
        for n,t in zip(a.indices,requested_micros):
            old=a.output/mode/f'frame_{int(t):016d}.png';new=a.output/mode/f'frame_{n:08d}.png';old.rename(new)
        results[mode]=result;print('completed',mode,flush=True)
    try:
        import cv2
    except ModuleNotFoundError:
        cv2 = None
        from PIL import Image
    import numpy as np
    frames=[]
    for n,t in zip(a.indices,micros):
        frame={'frame':n,'timestamp_microseconds':int(t),'split':'train'}
        for mode in results:
            path=(a.output/mode/f'frame_{n:08d}.png').resolve();frame[mode]=str(path);frame[mode+'_sha256']=sha(path)
        for i in range(2):
            mask=cv2.imread(frame[f'mask{i}'],cv2.IMREAD_GRAYSCALE) if cv2 else np.asarray(Image.open(frame[f'mask{i}']).convert('L'));image=cv2.imread(frame[f'lens{i}'],cv2.IMREAD_COLOR) if cv2 else np.asarray(Image.open(frame[f'lens{i}']).convert('RGB'))
            if mask is None or image is None or mask.shape!=(a.width//2,a.width) or image.shape!=(a.width//2,a.width,3) or np.any((mask!=0)&(mask!=255)) or np.any(image[mask==0]!=0):raise ValueError('Invalid physical-lens support')
        frames.append(frame)
    manifest={'source':str(a.source.resolve()),'source_sha256':sha(a.source),'width':a.width,'height':a.width//2,'backend':'GPU','stabilization':'OFF camera frame','rolling_shutter':'OFF','seam':'FIXED; independent lenses, no flow','timestamps':'exact target microseconds checked against exporter paired timestamps; packet PTS validated separately','selection':'timestamps with seek','seek_early_us':a.seek_early_us,'frames':frames}
    (a.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')


if __name__=='__main__':main()
