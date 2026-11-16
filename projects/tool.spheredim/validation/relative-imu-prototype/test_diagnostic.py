#!/usr/bin/env python3
"""Structural smoke tests for bounded spherical/IMU CPU reference."""
import json,subprocess,sys,tempfile
from pathlib import Path
src=Path(__file__).resolve().parent/'diagnostic.py'
with tempfile.TemporaryDirectory(prefix='sphere-imu-') as root:
 result={}
 for case in ('connected','weak-baseline','disconnected','wrong-imu','noisy-imu'):
  dest=Path(root)/case
  subprocess.run([sys.executable,str(src),'--case',case,'--output',str(dest),'--max-evals','200'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  d=json.loads((dest/'metrics.json').read_text());result[case]=d
  assert d['observations']>24 and d['first_camera_fixed'] and d['visual_only']['evaluations']<=200 and d['visual_plus_imu']['evaluations']<=200
  for key in ('initial','visual_only','visual_plus_imu'):
   assert d[key]['position_rms']>=0 and d[key]['relative_rotation_truth_median_deg']>=0
 assert result['connected']['visual_component_sizes']==[8]
 assert result['disconnected']['visual_component_sizes']==[4,4]
 assert result['weak-baseline']['baseline_scale']<result['connected']['baseline_scale']
 assert result['wrong-imu']['imu_bias_deg_per_edge']==4
 assert result['noisy-imu']['imu_true_noise_sigma_deg']>result['noisy-imu']['imu_claimed_sigma_deg']
 print('PASS bounded connected, weak-baseline, disconnected, biased-IMU and noisy-IMU checks; solver convergence is reported separately')
