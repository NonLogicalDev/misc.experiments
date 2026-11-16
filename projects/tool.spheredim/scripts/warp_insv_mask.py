#!/usr/bin/env python3
"""Warp a static camera-relative equirectangular mask to FLOW_STATE coordinates.

Input mask white marks areas to hide. Requires source FLOW_STATE stitch with
rolling shutter OFF, same frame numbering as the supplied fused orientation CSV.
Writes a lossless grayscale FFV1 mask video; use ffmpeg maskedmerge to apply it.
"""
import argparse,csv,json,subprocess,sys,time
import cv2
import numpy as np
from scipy.spatial.transform import Rotation

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('video',help='FLOW_STATE equirectangular video (rolling shutter OFF)')
p.add_argument('mask',help='static mask PNG in OFF/camera coordinates (white means hide), or top40 for top 40 percent')
p.add_argument('poses',help='orientation_frames_fused.csv for same source')
p.add_argument('output',help='lossless FFV1 mask video filename (.mkv)')
p.add_argument('--dilate',type=int,default=4,help='source-mask dilation radius in pixels (default: 4)')
p.add_argument('--transition-seconds',type=float,help='apply the additional top mask from this video PTS onward')
p.add_argument('--transition-top-fraction',type=float,help='fraction of source panorama height additionally masked after transition, e.g. 0.75')
a=p.parse_args()
if (a.transition_seconds is None) != (a.transition_top_fraction is None): p.error('provide both transition options')
if a.transition_seconds is not None and (not np.isfinite(a.transition_seconds) or a.transition_seconds < 0 or not 0 < a.transition_top_fraction <= 1): p.error('transition time must be nonnegative and top fraction in (0, 1]')
info=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=width,height,avg_frame_rate,nb_frames','-of','json',a.video]))['streams'][0]
w,h=int(info['width']),int(info['height']); rate=info['avg_frame_rate']; n=int(info['nb_frames'])
if rate in ('0/0','0') or n <= 0: raise ValueError('video needs constant frame rate and frame count metadata')
with open(a.poses,newline='') as f: rows=list(csv.DictReader(f))
if len(rows)!=n or any(int(row['frame'])!=i for i,row in enumerate(rows)): raise ValueError(f'frame mismatch: video {n}, CSV {len(rows)}; use the matching full video or trim both consistently')
if a.mask == 'top40':
 mask=np.zeros((h,w),dtype=np.uint8); mask[:int(np.ceil(0.4*h)),:]=255
else:
 mask=cv2.imread(a.mask,cv2.IMREAD_GRAYSCALE)
 if mask is None: raise ValueError('cannot read mask')
if mask.shape!=(h,w): raise ValueError(f'mask must be {w}x{h}, found {mask.shape[1]}x{mask.shape[0]}')
if a.dilate < 0: raise ValueError('dilation must be nonnegative')
def prepare_mask(mask):
 if a.dilate:
  radius=a.dilate
  wrapped=np.pad(mask,((0,0),(radius,radius)),mode='wrap')
  wrapped=np.pad(wrapped,((radius,radius),(0,0)),mode='edge')
  mask=cv2.dilate(wrapped,cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(2*radius+1,2*radius+1)))[radius:-radius,radius:-radius]
 # Wrap longitude only; do not wrap from one pole to the other.
 padded=np.pad(mask,((1,1),(1,1)),mode='edge'); padded[1:-1,0]=mask[:,-1];padded[1:-1,-1]=mask[:,0]
 padded[0,:]=padded[1,:];padded[-1,:]=padded[-2,:]
 return padded
base_mask=prepare_mask(mask)
late_mask=None
if a.transition_seconds is not None:
 late=mask.copy(); late[:int(np.ceil(a.transition_top_fraction*h)),:]=255
 late_mask=prepare_mask(late)
lon=(np.arange(w,dtype=np.float32)+.5)*(2*np.pi/w)
lat=np.pi/2-(np.arange(h,dtype=np.float32)+.5)*(np.pi/h)
c=np.cos(lat)[:,None]; x=c*np.cos(lon)[None,:]; y=-c*np.sin(lon)[None,:]; z=np.sin(lat)[:,None]
cmd=['ffmpeg','-v','error','-y','-f','rawvideo','-pixel_format','gray','-video_size',f'{w}x{h}','-framerate',rate,'-i','pipe:0','-c:v','ffv1','-level','3','-pix_fmt','gray',a.output]
proc=subprocess.Popen(cmd,stdin=subprocess.PIPE);start=time.monotonic()
try:
 for i,row in enumerate(rows):
  q=[float(row[k]) for k in ('q_x','q_y','q_z','q_w')]
  Q=Rotation.from_quat(q).as_matrix().T @ Rotation.from_euler('z',float(row['heading_rad'])).as_matrix()
  sx=Q[0,0]*x+Q[0,1]*y+Q[0,2]*z;sy=Q[1,0]*x+Q[1,1]*y+Q[1,2]*z;sz=Q[2,0]*x+Q[2,1]*y+Q[2,2]*z
  mx=(np.mod(np.arctan2(-sy,sx)*(w/(2*np.pi))-.5,w)+1).astype(np.float32)
  my=(np.arccos(np.clip(sz,-1,1))*(h/np.pi)-.5+1).astype(np.float32)
  selected=late_mask if late_mask is not None and float(row['video_pts_s']) >= a.transition_seconds else base_mask
  out=cv2.remap(selected,mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)
  proc.stdin.write(out.tobytes())
  if i%30==0 or i+1==n: print(json.dumps({'frame':i+1,'total':n,'elapsed_s':round(time.monotonic()-start,1)}),file=sys.stderr,flush=True)
 proc.stdin.close()
 if proc.wait()!=0: raise RuntimeError('ffmpeg mask encode failed')
except BaseException:
 proc.stdin.close();proc.terminate();proc.wait();raise
