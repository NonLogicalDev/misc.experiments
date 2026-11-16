#!/usr/bin/env python3
"""Run bounded feature matching and SfM on full equirectangular image frames."""
import argparse,json,os,re,shutil,struct,subprocess,sys,tempfile,time
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('spirula',type=Path);p.add_argument('dataset',type=Path);p.add_argument('workspace',type=Path)
p.add_argument('--native-progress',required=True,type=Path);p.add_argument('--status',required=True,type=Path);p.add_argument('--log',required=True,type=Path)
p.add_argument('--threads',type=int,default=4);p.add_argument('--decode-threads',type=int,default=2)
p.add_argument('--overlap',type=int,default=10);p.add_argument('--retrieval-features',type=int,default=128);p.add_argument('--retrieval-neighbors',type=int,default=8);p.add_argument('--min-free-gib',type=float,default=3.);p.add_argument('--dry-run',action='store_true')
a=p.parse_args()
if not a.spirula.is_file():p.error('Spirula executable not found')
images=a.dataset/'images';masks=a.dataset/'masks'
if not images.is_dir() or not masks.is_dir():p.error('dataset must contain images and masks')
imageset=sorted(f.name for f in images.glob('*.png'));maskset=sorted(f.name for f in masks.glob('*.png'))
if not imageset or imageset!=maskset:p.error('image and mask PNG filenames must match one-to-one')
def png_size(file):
 with file.open('rb') as f:header=f.read(24)
 if len(header)!=24 or header[:8]!=b'\x89PNG\r\n\x1a\n' or header[12:16]!=b'IHDR':raise ValueError(f'invalid PNG: {file}')
 return struct.unpack('>II',header[16:24])
try:
 size=png_size(images/imageset[0]);w,h=size
 if w!=2*h or h<1:raise ValueError('images must be full 2:1 equirectangular')
 for name in imageset:
  if png_size(images/name)!=size or png_size(masks/name)!=size:raise ValueError(f'image or mask size mismatch: {name}')
except (OSError,ValueError,struct.error) as error:p.error(str(error))
if a.workspace.exists():p.error('workspace must not exist; preserve earlier runs')
if min(a.threads,a.decode_threads,a.overlap,a.retrieval_neighbors)<1 or a.retrieval_features<16 or a.min_free_gib<0:p.error('invalid runtime limit')
maxdim=max(size);N=len(imageset)
cmd=[str(a.spirula),'sfm','auto',str(images),'-o',str(a.workspace),'--camera-model','equirectangular','--camera-mode','single','--masks',str(masks),'--data-type','video','--quality','medium','--max-image-size',str(maxdim),'--features','sift','--matcher','bruteforce','--pairs','sequential','--sequence','.','--overlap',str(a.overlap),'--quadratic-overlap','--prefilter-features',str(a.retrieval_features),'--prefilter-train',str(a.retrieval_features),'--prefilter-neighbors',str(a.retrieval_neighbors),'--threads',str(a.threads),'--decode-threads',str(a.decode_threads),'--progress-dir',str(a.native_progress)]
if a.dry_run:print(json.dumps({'image_count':N,'size':list(size),'command':cmd},indent=2));sys.exit(0)
for f in (a.status,a.log):f.parent.mkdir(parents=True,exist_ok=True)
start=time.monotonic();last={}
def publish(data):
 fd,name=tempfile.mkstemp(dir=a.status.parent,prefix='.spheredim-status-')
 with os.fdopen(fd,'w') as f:json.dump(data,f,indent=2);f.write('\n')
 os.replace(name,a.status)
def readnative():
 raw=(a.native_progress/'status.bin').read_bytes();magic,version,stage,flags,done,total,registered,images,points,models,reproj=struct.unpack('<4sIII6qd',raw)
 if magic!=b'VKPS' or version!=1:raise ValueError('unknown native progress format')
 with a.log.open('rb') as f:f.seek(max(0,a.log.stat().st_size-50000));tail=f.read().decode('utf-8','replace')
 stages=re.findall(r'\[(extract|match|map|merge|auto)\]',tail)
 return {'stage':stages[-1] if stages else 'sfm','native_stage_id':stage,'status':'running','partial':bool(flags&2),'metric':bool(flags&4),'done':done,'total':total,'registered':registered,'images':images,'points':points,'models':models,'mean_reprojection_px':reproj,'log':str(a.log),'workspace':str(a.workspace),'elapsed_seconds':time.monotonic()-start,'free_gib':shutil.disk_usage(a.workspace.parent).free/1024**3}
with a.log.open('a',buffering=1) as output:
 output.write(f'Native equirectangular SfM: {N} panoramas at {w}x{h}; sequential + quadratic neighbors and bounded content-based retrieval.\n')
 output.write('Command: '+json.dumps(cmd)+'\n');output.flush()
 env=dict(os.environ,SS_LANG='en');proc=subprocess.Popen(cmd,stdout=output,stderr=subprocess.STDOUT,env=env)
 try:
  while proc.poll() is None:
   try:last=readnative()
   except (OSError,ValueError,struct.error):last={'stage':'starting sfm','status':'running','done':0,'total':N,'registered':0,'images':N,'points':0,'log':str(a.log),'elapsed_seconds':time.monotonic()-start}
   if shutil.disk_usage(a.workspace.parent).free<a.min_free_gib*1024**3:
    output.write(f'Stopped: less than {a.min_free_gib:g} GiB free.\n');proc.terminate();proc.wait(timeout=30);last.update(status='failed',error='Stopped to protect disk space');publish(last);sys.exit(1)
   publish(last);time.sleep(1)
  try:last=readnative()
  except (OSError,ValueError,struct.error):pass
  last.update(status='complete' if proc.returncode==0 else 'failed',exit_code=proc.returncode,elapsed_seconds=time.monotonic()-start)
  if proc.returncode:last['error']=f'SfM exited with code {proc.returncode}; see log.'
  publish(last);sys.exit(proc.returncode)
 except KeyboardInterrupt:
  if proc.poll() is None:
   proc.terminate()
   try:proc.wait(timeout=30)
   except subprocess.TimeoutExpired:proc.kill();proc.wait()
  last.update(stage='paused',status='paused',error=None,elapsed_seconds=time.monotonic()-start)
  publish(last);sys.exit(130)
 except BaseException:
  if proc.poll() is None:proc.terminate()
  raise
