#!/usr/bin/env python3
"""Convert SphereDim OFF-video poses to match FLOW_STATE, rolling shutter off."""
import argparse,csv,json
import numpy as np
from scipy.spatial.transform import Rotation
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('poses_json');p.add_argument('fused_csv');p.add_argument('output_json')
a=p.parse_args()
with open(a.poses_json) as f: data=json.load(f)
if data.get('schema')!='spheredim-poses-v1' or data.get('camera_model')!='360DVO equirectangular': raise ValueError('expected 360DVO SphereDim poses')
with open(a.fused_csv,newline='') as f: imu=list(csv.DictReader(f))
times=np.array([float(row['video_pts_s']) for row in imu]); dt=float(np.median(np.diff(times)))
C=np.array([[0.,0.,-1.],[1.,0.,0.],[0.,-1.,0.]])
for row in data['frames']:
 if row['world_from_camera'] is None: continue
 t=float(row['time_seconds']);idx=int(np.argmin(abs(times-t)))
 if abs(times[idx]-t)>dt*.51: raise ValueError(f'pose time {t} has no matching orientation frame')
 sample=imu[idx];R=Rotation.from_quat([float(sample[k]) for k in ('q_x','q_y','q_z','q_w')]).as_matrix()
 Q=R.T@Rotation.from_euler('z',float(sample['heading_rad'])).as_matrix()
 M=np.asarray(row['world_from_camera'],dtype=float);M[:,:3]=M[:,:3]@C.T@Q@C;row['world_from_camera']=M.tolist()
data['note']=data.get('note','')+' Rotations adjusted to FLOW_STATE with rolling shutter disabled; positions unchanged. Heading is relative to the fused IMU estimate.'
with open(a.output_json,'x') as f: json.dump(data,f,indent=2);f.write('\n')
