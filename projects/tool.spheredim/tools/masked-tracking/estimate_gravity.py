#!/usr/bin/env python3
"""Estimate world-space gravity up from 360DVO OFF poses and X5 IMU fusion."""
import argparse,csv,json
import numpy as np
from scipy.spatial.transform import Rotation
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('poses');p.add_argument('imu');p.add_argument('output')
p.add_argument('--huber-degrees',type=float,default=10.)
a=p.parse_args()
if not 0<a.huber_degrees<90: p.error('Huber cutoff must be in (0, 90) degrees')
with open(a.poses) as f: track=json.load(f)
if track.get('schema')!='spheredim-poses-v1' or track.get('camera_model')!='360DVO equirectangular': raise ValueError('expected OFF 360DVO spheredim-poses-v1')
with open(a.imu,newline='') as f: imu=list(csv.DictReader(f))
times=np.array([float(row['video_pts_s']) for row in imu]);
if len(times)<2 or not np.isfinite(times).all() or not (np.diff(times)>0).all(): raise ValueError('invalid IMU frame PTS')
dt=np.median(np.diff(times));C=np.array([[0.,0.,-1.],[1.,0.,0.],[0.,-1.,0.]])
vectors=[];skipped=0;matching=[]
for row in track['frames']:
 if row['world_from_camera'] is None: skipped+=1;continue
 t=float(row['time_seconds']); i=int(np.searchsorted(times,t)); candidates=[j for j in (i-1,i) if 0<=j<len(times)]
 if not np.isfinite(t) or not candidates: raise ValueError('invalid pose time')
 j=min(candidates,key=lambda j:abs(times[j]-t))
 if abs(times[j]-t)>dt*.51: raise ValueError(f'pose at {t}s has no matching IMU frame')
 m=np.asarray(row['world_from_camera'],dtype=float)
 if m.shape!=(3,4) or not np.isfinite(m).all() or not np.allclose(m[:,:3].T@m[:,:3],np.eye(3),atol=1e-3) or np.linalg.det(m[:,:3])<.999: raise ValueError(f'invalid rotation at {t}s')
 q=np.array([float(imu[j][k]) for k in ('q_x','q_y','q_z','q_w')]);norm=np.linalg.norm(q)
 if not np.isfinite(norm) or abs(norm-1)>1e-3: raise ValueError(f'invalid IMU quaternion at {t}s')
 R=Rotation.from_quat(q).as_matrix();v=m[:,:3]@C.T@R.T@np.array([0.,0.,1.]);vectors.append(v/np.linalg.norm(v));matching.append(abs(times[j]-t))
if len(vectors)<3: raise ValueError('at least three matching tracked poses required')
V=np.stack(vectors);mean=V.mean(axis=0)
if np.linalg.norm(mean)<.1: raise ValueError('gravity estimates are too inconsistent to initialize')
up=mean/np.linalg.norm(mean);cut=np.deg2rad(a.huber_degrees)
for _ in range(100):
 angle=np.arccos(np.clip(V@up,-1,1));weights=np.minimum(1.,cut/np.maximum(angle,1e-12));new=weights@V;new/=np.linalg.norm(new)
 if np.linalg.norm(new-up)<1e-12: up=new;break
 up=new
angles=np.degrees(np.arccos(np.clip(V@up,-1,1)));result={'schema':'spheredim-gravity-v1','world_up':up.tolist(),'matched_poses':len(V),'skipped_unregistered':skipped,'huber_cutoff_degrees':a.huber_degrees,'angular_spread_degrees':{'median':float(np.median(angles)),'p90':float(np.percentile(angles,90)),'p95':float(np.percentile(angles,95)),'max':float(np.max(angles))},'fraction_above_huber_cutoff':float(np.mean(angles>a.huber_degrees)),'max_timestamp_difference_seconds':max(matching),'note':'Spread measures disagreement among matched tracked poses and IMU estimates, not absolute uncertainty or validated physical error. Assumes matching unmodified OFF footage and IMU timestamps.'}
with open(a.output,'x') as f:json.dump(result,f,indent=2);f.write('\n')
print(json.dumps(result,indent=2))
