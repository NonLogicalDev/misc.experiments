#!/usr/bin/env python3
"""Prepare full native equirectangular video frames and per-frame exclusion masks."""
import argparse, json, os, shutil, subprocess, tempfile, time
from pathlib import Path
import cv2
import numpy as np

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('video',type=Path);p.add_argument('mask_video',type=Path);p.add_argument('output',type=Path)
p.add_argument('--mask-polarity',required=True,choices=['white-exclude','white-keep'])
p.add_argument('--status',required=True,type=Path);p.add_argument('--log',required=True,type=Path)
p.add_argument('--guard-pixels',type=int,default=4);p.add_argument('--min-free-gib',type=float,default=4.)
a=p.parse_args()
if a.output.exists():p.error('output directory must not already exist')
if a.guard_pixels<0 or a.min_free_gib<0:p.error('guard-pixels and min-free-gib must be nonnegative')
for f in (a.video,a.mask_video):
 if not f.is_file():p.error(f'input not found: {f}')
for f in (a.status,a.log):f.parent.mkdir(parents=True,exist_ok=True)
raw=subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-show_frames','-show_entries','frame=best_effort_timestamp_time','-of','csv=p=0',str(a.video)],text=True)
pts=[]
for line in raw.splitlines():
 try:pts.append(float(line.split(',')[0]))
 except ValueError:pass
if not pts or not all(np.isfinite(pts)) or any(b<=x for x,b in zip(pts,pts[1:])):raise ValueError('video must have strictly increasing frame timestamps')
mask_raw=subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-show_frames','-show_entries','frame=best_effort_timestamp_time','-of','csv=p=0',str(a.mask_video)],text=True)
mask_pts=[]
for line in mask_raw.splitlines():
 try:mask_pts.append(float(line.split(',')[0]))
 except ValueError:pass
if len(mask_pts)!=len(pts) or not all(np.isfinite(mask_pts)) or any(b<=x for x,b in zip(mask_pts,mask_pts[1:])):raise ValueError('mask must have matching, strictly increasing frame timestamps')
if len(pts)>1:
 tolerance=float(np.median(np.diff(pts)))*.25
 if max(abs((x-pts[0])-(y-mask_pts[0])) for x,y in zip(pts,mask_pts))>tolerance:raise ValueError('mask and video frame timestamps do not align')
video=cv2.VideoCapture(str(a.video));mask=cv2.VideoCapture(str(a.mask_video))
if not video.isOpened() or not mask.isOpened():raise RuntimeError('video or mask failed to open')
w=int(video.get(cv2.CAP_PROP_FRAME_WIDTH));h=int(video.get(cv2.CAP_PROP_FRAME_HEIGHT));N=len(pts)
if w!=2*h:raise ValueError(f'video must be full 2:1 equirectangular; got {w}x{h}')
a.output.mkdir(parents=True);(a.output/'images').mkdir();(a.output/'masks').mkdir();start=time.monotonic();idx=0

def publish(stage,done,error=None):
 obj={'stage':stage,'status':'failed' if error else 'running','done':done,'total':N,'registered':0,'images':N,'points':0,'width':w,'height':h,'elapsed_seconds':time.monotonic()-start,'log':str(a.log),'error':error}
 fd,name=tempfile.mkstemp(dir=a.status.parent,prefix='.spheredim-status-')
 with os.fdopen(fd,'w') as f:json.dump(obj,f,indent=2);f.write('\n')
 os.replace(name,a.status)
try:
 with a.log.open('a',buffering=1) as log:
  log.write(f'Preparing {N} full {w}x{h} equirectangular frames and masks.\n')
  for idx in range(N):
   if idx%20==0 and shutil.disk_usage(a.output).free<a.min_free_gib*1024**3:raise RuntimeError(f'Less than {a.min_free_gib:g} GiB free')
   ok,im=video.read();ok2,m=mask.read()
   if not ok or not ok2:raise RuntimeError(f'video or mask ended at frame {idx}')
   if im.shape[:2]!=(h,w) or m.shape[:2]!=(h,w):raise RuntimeError(f'dimension mismatch at frame {idx}')
   gray=cv2.cvtColor(m,cv2.COLOR_BGR2GRAY) if m.ndim==3 else m
   # Any nonzero exclude-mask value or non-white keep-mask value is excluded.
   excluded=(gray>0 if a.mask_polarity=='white-exclude' else gray<255).astype('uint8')
   if a.guard_pixels:
    k=2*a.guard_pixels+1;excluded=cv2.dilate(excluded,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(k,k)))
   keep=(excluded==0).astype('uint8')*255;name=f'frame_{idx:06d}.png'
   if not cv2.imwrite(str(a.output/'images'/name),im,[cv2.IMWRITE_PNG_COMPRESSION,3]):raise RuntimeError('writing frame failed')
   if not cv2.imwrite(str(a.output/'masks'/name),keep,[cv2.IMWRITE_PNG_COMPRESSION,3]):raise RuntimeError('writing mask failed')
   if idx%10==0 or idx+1==N:log.write(f'preparing frames {idx+1}/{N} elapsed={time.monotonic()-start:.1f}s free_gib={shutil.disk_usage(a.output).free/1024**3:.2f}\n');publish('preparing frames',idx+1)
  extra,_=mask.read()
  if extra:raise RuntimeError('mask contains more frames than the video; ensure timing matches')
  manifest={'source_video':str(a.video.resolve()),'source_mask':str(a.mask_video.resolve()),'projection':'equirectangular','width':w,'height':h,'frame_count':N,'input_mask_polarity':a.mask_polarity,'mask':'white keep','guard_pixels':a.guard_pixels,'frames':[{'name':f'frame_{i:06d}.png','source_frame':i,'pts_seconds':t} for i,t in enumerate(pts)]}
  (a.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');log.write(f'Prepared {N} original-resolution panoramas and masks.\n');publish('frames ready',N)
except Exception as e:publish('preparing frames',idx,str(e));raise
finally:video.release();mask.release()
