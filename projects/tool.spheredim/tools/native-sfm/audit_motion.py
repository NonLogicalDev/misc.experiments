#!/usr/bin/env python3
"""Audit a paired spherical rig trajectory against its input rotation priors."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import numpy as np
import compare_rigs as c


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def angle(R):
    return math.degrees(math.acos(float(np.clip((np.trace(R)-1)/2,-1,1))))


def summary(values):
    if not values:return {'count':0}
    x=np.asarray(values);return {'count':len(x),'median':float(np.median(x)),'p90':float(np.percentile(x,90)),'p95':float(np.percentile(x,95)),'max':float(np.max(x))}


def load_priors(path):
    out={}
    with path.open(newline='') as f:
        for row in csv.DictReader(f):
            name=row['image'];q=np.array([float(row[k]) for k in ('qw','qx','qy','qz')]);sigma=float(row['sigma_degrees'])
            if name in out:raise ValueError(f'Duplicate prior {name}')
            if not np.isfinite(q).all() or np.linalg.norm(q)<1e-12 or not math.isfinite(sigma) or sigma<=0:raise ValueError(f'Invalid prior {name}')
            out[name]=c.rotation(q)
    return out


def audit(frames,poses,priors,angle_limit,speed_limit):
    if not math.isfinite(angle_limit) or angle_limit<=0 or not math.isfinite(speed_limit) or speed_limit<=0:raise ValueError('Thresholds must be positive finite values')
    ids=[f['source_frame'] for f in frames];times=[f['timestamp_microseconds'] for f in frames]
    if len(ids)<2 or ids!=sorted(set(ids)) or any(not isinstance(x,int) for x in ids+times) or any(a>=b for a,b in zip(times,times[1:])):raise ValueError('Expected unique sorted frames and increasing integer timestamps')
    expected={f'cam{j}/frame_{n:06}.png' for n in ids for j in (0,1)}
    for name,(R,C) in poses.items():
        if not np.isfinite(R).all() or not np.isfinite(C).all() or not np.allclose(R.T@R,np.eye(3),atol=1e-6) or not np.isclose(np.linalg.det(R),1,atol=1e-6):raise ValueError(f'Invalid pose {name}')
    for name,R in priors.items():
        if not np.isfinite(R).all():raise ValueError(f'Invalid prior {name}')
    if set(priors)!=expected:raise ValueError('Prior inventory differs from dataset manifest')
    names=[f'cam0/frame_{n:06}.png' for n in ids];valid=[x for x in names if x in poses]
    if not valid:raise ValueError('No cam0 poses available')
    # A rotates the reconstructed world basis into the prior world basis.
    M=sum((priors[n]@poses[n][0] for n in valid),np.zeros((3,3)))
    U,_,Vt=np.linalg.svd(M);D=np.eye(3);D[-1,-1]=np.linalg.det(U@Vt);A=U@D@Vt
    alignment={n:angle(priors[n].T@A@poses[n][0].T) for n in sorted(expected & set(poses))}
    pairs=[]
    for i in range(len(ids)-1):
        n0,n1=names[i:i+2];rec={'from_frame':ids[i],'to_frame':ids[i+1],'from_timestamp_microseconds':times[i],'to_timestamp_microseconds':times[i+1]}
        if n0 not in poses or n1 not in poses:rec['missing_images']=[n for n in (n0,n1) if n not in poses];pairs.append(rec);continue
        r0,r1=poses[n0][0].T,poses[n1][0].T;p0,p1=priors[n0],priors[n1]
        delta=r0.T@r1;reference=p0.T@p1;dt=(times[i+1]-times[i])/1e6;distance=float(np.linalg.norm(poses[n1][1]-poses[n0][1]));err=angle(delta.T@reference)
        rec.update(rotation_disagreement_degrees=err,model_rotation_degrees=angle(delta),prior_rotation_degrees=angle(reference),distance=distance,speed=distance/dt,rotation_flag=err>angle_limit,speed_flag=distance/dt>speed_limit);pairs.append(rec)
    observed=set(poses);baseline=c.rig_stats(poses);orientation_values=[x['rotation_disagreement_degrees'] for x in pairs if 'rotation_disagreement_degrees' in x]
    return {'coverage':{'expected_frames':len(ids),'expected_images':len(expected),'registered_expected_images':len(expected&observed),'missing_images':sorted(expected-observed),'unexpected_images':sorted(observed-expected),'frames_both_lenses':sum(all(f'cam{j}/frame_{n:06}.png' in observed for j in (0,1)) for n in ids),'frames_cam0':len(valid)},'fixed_rig':baseline,'world_alignment':{'prior_world_from_model_world':A.tolist(),'residual_degrees':summary(list(alignment.values())),'per_image_degrees':alignment},'adjacent_rotation_disagreement_degrees':summary(orientation_values),'distance':summary([x['distance'] for x in pairs if 'distance' in x]),'speed':summary([x['speed'] for x in pairs if 'speed' in x]),'intervals':pairs}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('model',type=Path);p.add_argument('manifest',type=Path);p.add_argument('priors',type=Path);p.add_argument('output',type=Path);p.add_argument('--angle-degrees',type=float,default=5,help='Report-only angular flag, degrees (default 5; not ground truth)');p.add_argument('--speed',type=float,default=2,help='Report-only speed flag in model units/s (default 2; scale not verified)');a=p.parse_args()
    image_file=c.model_image_file(a.model)
    # Existing text reader does not detect duplicate image names.
    if image_file.suffix=='.txt':
        lines=[x for x in image_file.read_text().splitlines() if not x.startswith('#')];headers=lines[::2];names=[x.split()[9] for x in headers if len(x.split())>=10]
        if len(names)!=len(set(names)):raise ValueError('Duplicate model image')
    poses=c.read_poses(a.model);priors=load_priors(a.priors);manifest=json.loads(a.manifest.read_text());result=audit(manifest['frames'],poses,priors,a.angle_degrees,a.speed)
    report={'method':'Model world aligned to prior world by one fitted rotation using cam0 orientations. Adjacent comparisons are invariant to that world alignment. Priors entered reconstruction and are not independent ground truth. Speed and distance use model units; metric interpretation is unverified. Flags are report-only.','thresholds':{'rotation_degrees':a.angle_degrees,'speed_model_units_per_second':a.speed},'sha256':{'images':digest(image_file),'manifest':digest(a.manifest),'priors':digest(a.priors),'audit_script':digest(Path(__file__)),'pose_reader':digest(Path(c.__file__))},**result}
    with a.output.open('x') as f:json.dump(report,f,indent=2,allow_nan=False);f.write('\n')
if __name__=='__main__':main()
