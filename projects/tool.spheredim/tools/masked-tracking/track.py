"""Track an equirectangular video and publish partial camera and sparse point snapshots."""
import argparse, csv, json, math, os, sys, time
from pathlib import Path
import cv2
import numpy as np
from scipy.spatial.transform import Rotation
import torch
from dpvo.config import cfg
from dpvo.dpvo import DPVO
from portable_demo import choose_device
from masking import install

p=argparse.ArgumentParser()
p.add_argument('video',type=Path); p.add_argument('output',type=Path)
p.add_argument('--weights',type=Path,required=True); p.add_argument('--device',default='mps')
p.add_argument('--width',type=int,default=1024); p.add_argument('--patches',type=int,default=96)
p.add_argument('--mask-top',type=float,required=True,help='Fraction of image height to black out at top')
p.add_argument('--mask-guard',type=float,required=True,help='Additional fraction excluded from tracking')
p.add_argument('--stride',type=int,default=5); p.add_argument('--snapshot-every',type=int,default=20)
a=p.parse_args()
if a.output.exists() and any(a.output.iterdir()): p.error('output directory must be empty')
a.output.mkdir(parents=True,exist_ok=True)
if a.width < 128 or a.width % 32 or a.stride < 1 or a.snapshot_every < 1: p.error('Invalid width, stride, or snapshot interval')
if not (0 <= a.mask_top < 1 and 0 <= a.mask_guard < 1 and a.mask_top + a.mask_guard < .9): p.error('mask fractions must be nonnegative and sum to less than 0.9')
device=choose_device(a.device); cap=cv2.VideoCapture(str(a.video))
w=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH));h=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT));fps=cap.get(cv2.CAP_PROP_FPS); frame_count=int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
if not cap.isOpened() or w != 2*h or not math.isfinite(fps) or fps<=0: raise RuntimeError('Expected readable 2:1 equirectangular video')
cfg.merge_from_file(str(Path(__import__('dpvo').__file__).parent.parent/'config/360.yaml'));cfg.MIXED_PRECISION=False;cfg.PATCHES_PER_FRAME=a.patches;cfg.BUFFER_SIZE=512
tracker=DPVO(cfg,str(a.weights),ht=a.width//2,wd=a.width,device=device)
install(tracker,a.mask_top+a.mask_guard)
intr=torch.tensor([a.width/(2*math.pi),-a.width/(2*math.pi),a.width/2,a.width/4],dtype=torch.float32,device=device)
torch.manual_seed(0); started=time.monotonic(); used=0; source=0
estimated=math.ceil(frame_count/a.stride) if frame_count>0 else None

def progress(stage, error=None):
    elapsed=time.monotonic()-started
    eta=(elapsed/used)*(estimated-used) if used and estimated and stage=='tracking' else None
    data={'stage':stage,'sampled':used,'total':estimated,'video_time_seconds':source/fps,
          'elapsed_seconds':elapsed,'eta_seconds':max(0,eta) if eta is not None else None,
          'initialized':tracker.is_initialized,'mask_top':a.mask_top,'mask_guard':a.mask_guard,'poses_file':('poses.json' if stage=='complete' else 'poses-progress.json'),
          'points_file':('sparse.ply' if stage=='complete' else 'sparse-progress.ply'),'error':error}
    target=a.output/'progress.json';tmp=a.output/'progress.json.tmp'
    tmp.write_text(json.dumps(data,indent=2)+'\n');os.replace(tmp,target)

progress('initializing')

def snapshot(final=False):
    poses,timestamps=tracker.terminate(); rows=[]
    for i,(pose,t) in enumerate(zip(poses,timestamps)):
        matrix=np.column_stack((Rotation.from_quat(pose[3:7]).as_matrix(),pose[:3]))
        rows.append({'frame':i,'time_seconds':float(t),'image':f'{i:06}','world_from_camera':matrix.tolist()})
    data={'schema':'spheredim-poses-v1','input_video':str(a.video.resolve()),'sampling_fps':fps/a.stride,'camera_model':'360DVO equirectangular','coordinates':'camera-to-world 3x4 row-major; camera x right, y down, z forward; arbitrary world axes and scale','registered':len(rows),'sampled':len(rows),'frames':rows,'note':'Some removed frames are reconstructed from relative motion. Partial snapshots may change as optimization continues.','complete':final}
    target=a.output/('poses.json' if final else 'poses-progress.json');tmp=target.with_suffix('.json.tmp');tmp.write_text(json.dumps(data,indent=2)+'\n');os.replace(tmp,target)
    if final:
        with (a.output/'poses.csv').open('w',newline='') as f:
            writer=csv.writer(f);writer.writerow(['frame','time_seconds','image','registered']+[f'm{r}{c}' for r in range(3) for c in range(4)])
            for row in rows:writer.writerow([row['frame'],row['time_seconds'],row['image'],1]+[v for line in row['world_from_camera'] for v in line])
    points=tracker.points_[:tracker.m].detach().cpu().numpy();colors=tracker.colors_.reshape(-1,3)[:tracker.m].detach().cpu().numpy()
    valid=np.isfinite(points).all(axis=1)&(np.linalg.norm(points,axis=1)>1e-8)&(np.abs(points).max(axis=1)<1e5)
    points,colors=points[valid],colors[valid]
    target=a.output/('sparse.ply' if final else 'sparse-progress.ply');tmp=target.with_suffix('.ply.tmp')
    with tmp.open('w') as f:
        f.write('ply\nformat ascii 1.0\ncomment Sparse 360DVO patches; arbitrary scale and outliers possible\n'+f'element vertex {len(points)}\nproperty float x\nproperty float y\nproperty float z\nproperty uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n')
        for pt,color in zip(points,colors):f.write(f'{pt[0]:.7g} {pt[1]:.7g} {pt[2]:.7g} {int(color[0])} {int(color[1])} {int(color[2])}\n')
    os.replace(tmp,target)
    print(f'SNAPSHOT frames={len(rows)} points={len(points)} final={final}',flush=True)

with torch.no_grad():
    try:
        while True:
            ok,frame=cap.read()
            if not ok:break
            if source%a.stride==0:
                if tracker.n>=tracker.N-1:raise RuntimeError(f'Tracker reached {tracker.N} keyframe buffer limit')
                frame[:math.ceil(frame.shape[0]*a.mask_top)] = 0
                resized=cv2.resize(frame,(a.width,a.width//2),interpolation=cv2.INTER_AREA)
                tracker.set_mask_frame(resized)
                image=torch.from_numpy(resized).permute(2,0,1).to(device)
                tracker(source/fps,image,intr);used+=1
                elapsed=time.monotonic()-started; estimated=math.ceil(frame_count/a.stride) if frame_count>0 else None
                remaining=(elapsed/used)*(estimated-used) if estimated else None
                progress('tracking')
                print(f'TRACKING sampled={used}/{estimated or "?"} video_time={source/fps:.1f}s elapsed={elapsed:.1f}s eta={remaining:.1f}s' if remaining is not None else f'TRACKING sampled={used} video_time={source/fps:.1f}s elapsed={elapsed:.1f}s',flush=True)
                if tracker.is_initialized and used%a.snapshot_every==0:snapshot()
            source+=1
        if not tracker.is_initialized: raise RuntimeError('360DVO did not initialize; motion or texture insufficient')
        progress('refining')
        print('REFINING iterations=12',flush=True)
        for i in range(12):tracker.update();print(f'REFINING {i+1}/12',flush=True)
        snapshot(final=True)
        progress('complete')
    except Exception as error:
        progress('failed',str(error))
        raise
    finally:cap.release()
print('COMPLETE',flush=True)
