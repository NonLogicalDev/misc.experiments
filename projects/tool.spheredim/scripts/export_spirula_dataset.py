#!/usr/bin/env python3
"""Create a native ERP COLMAP-text dataset from 360DVO poses and video."""
import argparse,csv,json,math,shutil,subprocess
from pathlib import Path
import cv2,numpy as np
from scipy.spatial.transform import Rotation
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('video',type=Path);p.add_argument('poses',type=Path);p.add_argument('seed',type=Path);p.add_argument('output',type=Path)
p.add_argument('--pose-step',type=int,default=5,help='keep every Nth pose, then assign holdouts')
p.add_argument('--holdout-every',type=int,default=8,help='every Nth selected pose held out (0 disables)')
p.add_argument('--width',type=int,default=1024,help='output image width; height is half')
p.add_argument('--stop-before',type=float,default=float('inf'),help='exclude timestamps at or after this time')
p.add_argument('--mask-top',type=float,required=True,help='fraction of each source frame masked at the top; does not detect people');p.add_argument('--dilate',type=int,default=4,help='source pixel radius')
a=p.parse_args()
if a.pose_step<1 or a.holdout_every<0 or a.width<32 or a.width%2 or not 0<=a.mask_top<=1 or a.dilate<0: p.error('invalid sampling, width, or mask')
if a.output.exists():raise ValueError('output must not already exist')
with a.poses.open() as f: track=json.load(f)
if track.get('schema')!='spheredim-poses-v1' or track.get('camera_model')!='360DVO equirectangular':raise ValueError('expected 360DVO poses')
info=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=width,height,nb_frames,avg_frame_rate','-of','json',str(a.video)]))['streams'][0]
w0,h0=int(info['width']),int(info['height']);w,h=a.width,a.width//2
if w0!=2*h0:raise ValueError('input must be 2:1 ERP')
rate=info['avg_frame_rate'].split('/');fps=int(rate[0])/int(rate[1])
probe=subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-show_frames','-show_entries','frame=best_effort_timestamp_time','-of','csv=p=0',str(a.video)],text=True)
pts=[]
for line in probe.splitlines():
 try: pts.append(float(line.split(',')[0]))
 except ValueError: pass
pts=np.asarray(pts)
if len(pts)!=int(info['nb_frames']) or not np.isfinite(pts).all() or not (np.diff(pts)>0).all():raise ValueError('video frame timestamp metadata invalid')
selected=[]
for pos,row in enumerate(track['frames']):
 if pos%a.pose_step or row['world_from_camera'] is None:continue
 t=float(row['time_seconds'])
 if t>=a.stop_before:continue
 j=int(np.argmin(abs(pts-t)))
 if abs(pts[j]-t)>.51/fps:raise ValueError(f'pose {t} does not match a video frame')
 M=np.asarray(row['world_from_camera'],dtype=float)
 if M.shape!=(3,4) or not np.isfinite(M).all() or not np.allclose(M[:,:3].T@M[:,:3],np.eye(3),atol=.001) or np.linalg.det(M[:,:3])<.999:raise ValueError('invalid pose')
 if selected and j<=selected[-1][0]:raise ValueError('pose times must map to unique ordered source frames')
 selected.append((j,t,M))
if len(selected)<2:raise ValueError('not enough matched frames')
a.output.mkdir();(a.output/'images').mkdir();(a.output/'masks').mkdir();(a.output/'holdout').mkdir();(a.output/'holdout'/'images').mkdir();(a.output/'holdout'/'masks').mkdir();(a.output/'sparse'/'0').mkdir(parents=True)
shutil.copyfile(a.seed,a.output/'seed.ply')
mask=np.full((h,w),255,dtype=np.uint8);masked_rows=min(h,math.ceil((math.ceil(a.mask_top*h0)+a.dilate)*h/h0));mask[:masked_rows]=0
cap=cv2.VideoCapture(str(a.video));assert cap.isOpened();records=[];lines=[]
for k,(idx,t,M) in enumerate(selected):
 hold=a.holdout_every>0 and k%a.holdout_every==0
 # COLMAP text stores world->camera rotation as Hamilton (w,x,y,z).
 Rcw=M[:,:3];center=M[:,3];Rwc=Rcw.T;twc=-Rwc@center;q=Rotation.from_matrix(Rwc).as_quat();name=f'frame_{idx:06d}.png'
 if not cap.set(cv2.CAP_PROP_POS_FRAMES,idx):raise RuntimeError(f'cannot seek {idx}')
 ok,frame=cap.read()
 if not ok:raise RuntimeError(f'cannot decode {idx}')
 frame=cv2.resize(frame,(w,h),interpolation=cv2.INTER_AREA)
 root=a.output/'holdout' if hold else a.output
 if not cv2.imwrite(str(root/'images'/name),frame) or not cv2.imwrite(str(root/'masks'/name),mask):raise RuntimeError('image write failed')
 if not hold:
  image_id=len(lines)+1
  lines.append(f'{image_id} {q[3]:.17g} {q[0]:.17g} {q[1]:.17g} {q[2]:.17g} {twc[0]:.17g} {twc[1]:.17g} {twc[2]:.17g} 1 {name}\n\n')
 records.append({'file':name,'source_frame':idx,'video_pts_s':float(pts[idx]),'pose_time_s':t,'split':'heldout' if hold else 'train','world_from_camera':M.tolist()})
cap.release();recon=a.output/'sparse'/'0'
(recon/'cameras.txt').write_text(f'1 EQUIRECTANGULAR {w} {h} {w} {h}\n')
(recon/'images.txt').write_text(''.join(lines))
(recon/'points3D.txt').write_text('# seed.ply is supplied via --seed-pointcloud\n')
(a.output/'manifest.json').write_text(json.dumps({'video':str(a.video.resolve()),'poses':str(a.poses.resolve()),'seed':str(a.seed.resolve()),'mask_white_means':'keep','mask_top_fraction':a.mask_top,'source_mask_dilation_px':a.dilate,'output_masked_rows':masked_rows,'fps':fps,'frames':records},indent=2)+'\n')
print(json.dumps({'training':len(lines),'heldout':len(records)-len(lines),'matched_frames':len(records),'masked_rows':masked_rows,'output':str(a.output)}))
