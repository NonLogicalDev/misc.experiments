#!/usr/bin/env python3
"""Stage an unchanged physical-rig scene for a bounded 13-pose render sweep."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import cv2
import numpy as np
from scipy.spatial.transform import Rotation
import compare_rigs as rig
from audit_seed_gauge import read_erp_cameras
import compare_density_models as modelio


def validate_original_cameras(path):
    cameras = read_erp_cameras(path)
    if any(values[:2] != (1024, 512) or not np.allclose(values[2:], [1024, 512], rtol=0, atol=1e-9) for values in cameras.values()):
        raise ValueError('Expected full-sphere original 1024x512 ERP cameras')
    return cameras


def candidate_poses(poses, axis, angle, translation):
    """Rotate both cameras about cam0 and translate along cam0 body axes."""
    R0,C0=poses[0]; local=Rotation.from_rotvec(np.eye(3)[axis]*angle).as_matrix();world=R0.T@local@R0;move=R0.T@np.asarray(translation)
    return [(R@world.T,C0+world@(C-C0)+move) for R,C in poses]


def pose_row(image_id, name, camera_id, pose):
    R,C=pose;quat=Rotation.from_matrix(R).as_quat();t=-R@C
    return ' '.join(map(str,[image_id,quat[3],quat[0],quat[1],quat[2],*t,camera_id,name]))


def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for chunk in iter(lambda:f.read(1048576),b''):h.update(chunk)
    return h.hexdigest()


def stage(prepared,model,base_plan,output):
    prepared=Path(prepared).resolve(strict=True);model=Path(model).resolve(strict=True);base_plan=Path(base_plan).resolve(strict=True);output=Path(output).resolve()
    if output.exists():raise FileExistsError(output)
    manifest=json.loads((prepared/'manifest.json').read_text());rows={r['name']:r for r in manifest['frames']};names=['train_001500_cam0.png','train_001500_cam1.png'];train='train_001495_cam0.png'
    if any(n not in rows or rows[n]['split']!='train' for n in names+[train]):raise ValueError('Expected original training captures')
    camera_text=(prepared/'sparse/0/cameras.txt').read_text();camera_lines=[line.split() for line in camera_text.splitlines() if line and not line.startswith('#')]
    if any(len(r)!=6 or r[1]!='EQUIRECTANGULAR' or tuple(map(float,r[2:]))!=(2048.,1024.,2048.,1024.) for r in camera_lines):raise ValueError('Expected native full-sphere cameras')
    validate_original_cameras(model/'cameras.bin')
    poses=rig.read_binary_poses(model/'images.bin')
    prepared_poses=rig.read_poses(prepared/'sparse/0')
    for name in names+[train]:
        original=poses[rows[name]['source_name']]; staged=prepared_poses[name]
        if not all(np.allclose(a,b,rtol=0,atol=1e-8) for a,b in zip(original,staged)):raise ValueError(f'Prepared pose differs from original model: {name}')
    ref=[poses[rows[n]['source_name']] for n in names];obs=modelio.observations(model/'images.bin');pts=modelio.points(model/'points3D.bin');depths=[]
    # Model coordinates and native poses are the unscaled, original gauge.
    for n,(_,C) in zip(names,ref):
        mask=cv2.imread(str(prepared/'masks'/n),0)
        if mask is None or mask.shape!=(1024,2048):raise ValueError('Bad source mask')
        for (x,y),pid in obs[rows[n]['source_name']].items():
            ix=int(round(2*x));iy=int(round(2*y))
            if 0<=ix<2048 and 0<=iy<1024 and mask[iy,ix]==255 and pid in pts:depths.append(float(np.linalg.norm(pts[pid]-C)))
    if len(depths)<10:raise ValueError('Insufficient observed sparse depths')
    median=float(np.median(depths));step=.002*median;rot=np.deg2rad(.1)
    specs=[('center',0,0.,np.zeros(3))]
    for axis in range(3):
        for sign in (-1,1):specs.append((f'r{axis}_{sign:+d}',axis,sign*rot,np.zeros(3)))
    for axis in range(3):
        for sign in (-1,1):
            v=np.zeros(3);v[axis]=sign*step;specs.append((f't{axis}_{sign:+d}',axis,0.,v))
    base=json.loads(base_plan.read_text());cmd=base['zero_command'].copy();source_ply=Path(base['source_ply'])
    transform=json.loads((base_plan.parent/'zero/scene_transform.json').read_text())['train_from_world']['matrix_4x4']
    if not np.allclose(transform,np.eye(4),rtol=0,atol=1e-12):raise ValueError('Original model-to-training gauge is not identity')
    if sha(source_ply)!=base['source_ply_sha256'] or sha(cmd[0])!=base['binary_sha256']:raise ValueError('Source model or trainer hash mismatch')
    output.mkdir(parents=True);data=output/'data';(data/'images').mkdir(parents=True);(data/'masks').mkdir();(data/'sparse/0').mkdir(parents=True)
    for fname in ('sparse/0/cameras.txt','seed.ply'):os.link(prepared/fname,data/fname)
    (data/'sparse/0/points3D.txt').write_text('# seed supplied as PLY\n');lines=[];evidence=[]
    trainpose=poses[rows[train]['source_name']];lines.extend([pose_row(1,train,rows[train]['colmap_camera_id'],trainpose),''])
    for folder in ('images','masks'):os.link(prepared/folder/train,data/folder/train)
    for idx,(label,axis,angle,v) in enumerate(specs):
        posepair=candidate_poses(ref,axis,angle,v)
        for lens,(source,pose) in enumerate(zip(names,posepair)):
            name=f'eval_{idx:02d}_cam{lens}.png';lines.extend([pose_row(100+2*idx+lens,name,rows[source]['colmap_camera_id'],pose),''])
            for folder in ('images','masks'):os.link(prepared/folder/source,data/folder/name)
            evidence.append({'candidate':label,'lens':lens,'name':name,'pose_row':lines[-2]})
    (data/'sparse/0/images.txt').write_text('\n'.join(lines)+'\n')
    for key,value in [('--data',str(data)),('--output-dir-prefix',str(output)),('--output-dir-name','render'),('--steps-per-save','0'),('--save-eval-images','0')]:cmd[cmd.index(key)+1]=value
    report={'method':'13 zero-update common-body perturbations; training frame1500 in both lenses. Full ERP original gauge, raw masked pixels, no appearance or image alignment. Existing SfM used all frames; sensitivity is not an independently validated pose.','command':cmd,'median_observed_depth_model_units':median,'depth_observations':len(depths),'translation_step_model_units':step,'rotation_step_degrees':.1,'candidates':evidence,'source_ply_sha256':sha(source_ply),'binary_sha256':sha(cmd[0]),'source_manifest_sha256':sha(prepared/'manifest.json'),'source_scene_transform_sha256':sha(base_plan.parent/'zero/scene_transform.json'),'model_cameras_sha256':sha(model/'cameras.bin'),'model_images_sha256':sha(model/'images.bin'),'model_points_sha256':sha(model/'points3D.bin'),'source_hashes':{n:{k:sha(prepared/k/n) for k in ('images','masks')} for n in names+[train]},'camera_file_sha256':sha(prepared/'sparse/0/cameras.txt'),'staged_pose_file_sha256':sha(data/'sparse/0/images.txt')}
    (output/'plan.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'depth':median,'translation_step':step,'count':len(evidence),'command':cmd},indent=2))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('prepared');p.add_argument('model');p.add_argument('base_plan');p.add_argument('output');a=p.parse_args();stage(a.prepared,a.model,a.base_plan,a.output)
if __name__=='__main__':main()
