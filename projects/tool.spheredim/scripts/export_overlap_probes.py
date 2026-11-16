#!/usr/bin/env python3
"""Export full-sphere separate lens measurements in the camera frame."""
import argparse, hashlib, json, os, re, subprocess, sys
from pathlib import Path

def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''): h.update(b)
 return h.hexdigest()

def worker(a):
 import insta360_rs as ins
 c=ins.StitchConfig(backend=ins.ProcessingBackend.GPU,stabilization=ins.Stabilization.OFF,rolling_shutter=ins.RollingShutterCorrection.OFF,seam_mode=ins.SeamMode.FIXED,width=a.width,height=a.width//2)
 j=ins.start_export_frames(str(a.source),str(a.output),indices=a.indices,config=c,format=ins.ImageFormat.PNG); r=j.wait()
 print(json.dumps({'outputs':[str(x) for x in r.outputs],'backend':str(r.backend.selected)}))

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',required=True,type=Path);p.add_argument('--output',required=True,type=Path);p.add_argument('--indices',type=int,nargs='+',required=True);p.add_argument('--validation',type=int,nargs='+',required=True);p.add_argument('--width',type=int,default=2048);p.add_argument('--worker',action='store_true',help=argparse.SUPPRESS);a=p.parse_args()
 if a.worker:return worker(a)
 if a.output.exists():p.error('output exists')
 if len(set(a.indices))!=len(a.indices) or sorted(a.indices)!=a.indices or not set(a.validation).issubset(a.indices):p.error('indices must be unique, sorted and include validation')
 a.output.mkdir(parents=True); results={}
 for mode in ('lens0','lens1','mask0','mask1'):
  e=os.environ.copy();e['SPHEREDIM_OBSERVATION_MODE']=mode
  cmd=[sys.executable,__file__,'--worker','--source',str(a.source),'--output',str(a.output/mode),'--width',str(a.width),'--indices',*map(str,a.indices),'--validation',*map(str,a.validation)]
  r=subprocess.run(cmd,env=e,text=True,capture_output=True)
  if r.returncode: raise RuntimeError(f'{mode} failed: {r.stderr}')
  result=json.loads(r.stdout.strip().splitlines()[-1]);result['timestamps']=[(int(x),int(y)) for x,y in re.findall(r'SPHEREDIM_FRAME (\d+) (-?\d+)',r.stderr)]
  if len(result['timestamps'])!=len(a.indices) or 'GPU' not in result['backend']:raise ValueError('missing timestamps or GPU')
  results[mode]=result;print('completed',mode,flush=True)
 if any(results[k]['timestamps']!=results['lens0']['timestamps'] for k in results):raise ValueError('passes have mismatched timestamps')
 from PIL import Image
 import numpy as np
 frames=[]
 for idx,ts in results['lens0']['timestamps']:
  f={'frame':idx,'timestamp_microseconds':ts,'split':'validation' if idx in a.validation else 'train'}
  for k in results:
   path=a.output/k/f'frame_{idx:08d}.png'; f[k]=str(path.resolve());f[k+'_sha256']=sha(path)
  for i in range(2):
   mask=np.asarray(Image.open(f[f'mask{i}']).convert('L')); image=np.asarray(Image.open(f[f'lens{i}']).convert('RGB'))
   if np.any((mask!=0)&(mask!=255)) or np.any(image[mask==0]!=0):raise ValueError('invalid support frame')
  frames.append(f)
 manifest={'source':str(a.source.resolve()),'source_sha256':sha(a.source),'width':a.width,'height':a.width//2,'backend':'GPU','stabilization':'OFF camera frame','rolling_shutter':'OFF','seam':'FIXED; independent lenses, no flow','timestamps':'exporter paired microseconds, not proof of physical synchronization','frames':frames}
 (a.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
if __name__=='__main__':main()
