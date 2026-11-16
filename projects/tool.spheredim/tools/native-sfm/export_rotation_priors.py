#!/usr/bin/env python3
"""Export synchronized fused orientations as soft per-image camera-to-world priors."""
import argparse
import csv
from decimal import Decimal,InvalidOperation
import hashlib
import io
import json
import math
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation

BODY_FROM_CV=np.array([[0.,0.,-1.],[1.,0.,0.],[0.,-1.,0.]])


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def quaternion_rotation(values):
    q=np.asarray(values,dtype=float)
    if q.shape!=(4,) or not np.all(np.isfinite(q)) or abs(np.linalg.norm(q)-1)>1e-5:raise ValueError('Quaternion must be finite and unit length (wxyz)')
    return Rotation.from_quat([q[1],q[2],q[3],q[0]]).as_matrix()


def build_priors(dataset,rig,fused_rows,sigma):
    if not math.isfinite(sigma) or sigma<=0:raise ValueError('Sigma must be finite and positive')
    if len(rig['rigs'])!=1:raise ValueError('Exactly one rig is required')
    members=rig['rigs'][0]['members'];by_member={r['prefix']:r for r in members}
    if len(by_member)!=len(members) or set(by_member)!={'cam0','cam1'}:raise ValueError('Expected unique cam0 and cam1 rig members')
    if not all(m.get('fixed') is True for m in members):raise ValueError('Rig member rotations must be fixed')
    rig_rotation={name:quaternion_rotation(entry['rotation']) for name,entry in by_member.items()}
    if not np.allclose(rig_rotation['cam0'],np.eye(3),atol=1e-10):raise ValueError('cam0 must be reference rig orientation')
    fused={}
    for row in fused_rows:
        frame=int(row['frame'])
        if frame in fused:raise ValueError(f'Duplicate fused frame {frame}')
        fused[frame]=row
    frames=dataset['frames'];seen=set();result=[];provenance=[]
    for frame in frames:
        index=frame['source_frame']
        if index in seen:raise ValueError(f'Duplicate dataset frame {index}')
        seen.add(index)
        if index not in fused:raise ValueError(f'Missing fused frame {index}')
        if set(frame['lenses'])!=set(by_member):raise ValueError(f'Frame {index} lacks a rig lens')
        src=fused[index]
        try:timestamp=Decimal(src['video_pts_s'])*Decimal(1000000)
        except InvalidOperation as e:raise ValueError('Invalid fused timestamp') from e
        if not timestamp.is_finite() or timestamp!=Decimal(frame['timestamp_microseconds']):raise ValueError(f'Frame {index} timestamp mismatch')
        body=quaternion_rotation([float(src[k]) for k in ('q_w','q_x','q_y','q_z')])
        for name in ('cam0','cam1'):
            world_from_camera=body@BODY_FROM_CV@rig_rotation[name].T
            q=Rotation.from_matrix(world_from_camera).as_quat()
            if q[3]<0:q=-q
            image=f'{name}/frame_{index:06d}.png'
            result.append({'image':image,'qw':float(q[3]),'qx':float(q[0]),'qy':float(q[1]),'qz':float(q[2]),'sigma_degrees':sigma})
            provenance.append({'image':image,'source_frame':index,'timestamp_microseconds':frame['timestamp_microseconds'],'fused_video_pts_s':src['video_pts_s'],'image_sha256':frame['lenses'][name]['image_sha256'],'camera_from_rig_rotation':rig_rotation[name].tolist()})
    return result,provenance


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('dataset_manifest',type=Path);p.add_argument('rig_config',type=Path);p.add_argument('fused_csv',type=Path);p.add_argument('output_csv',type=Path);p.add_argument('provenance_json',type=Path);p.add_argument('--sigma-degrees',type=float,default=1.0,help='Assumed soft one-sigma orientation uncertainty; default 1 degree, not measured')
    a=p.parse_args();inputs=[v.resolve(strict=True) for v in (a.dataset_manifest,a.rig_config,a.fused_csv)];manifest,rig_path,fused=inputs
    if a.output_csv.exists() or a.provenance_json.exists() or a.output_csv.resolve()==a.provenance_json.resolve():p.error('Both output paths must be new and distinct')
    dataset=json.loads(manifest.read_text());rig=json.loads(rig_path.read_text())
    if digest(fused)!=dataset['fused_csv_sha256']:raise ValueError('Fused CSV hash differs from dataset provenance')
    with fused.open(newline='') as f:rows=list(csv.DictReader(f))
    priors,images=build_priors(dataset,rig,rows,a.sigma_degrees)
    for item in images:
        path=manifest.parent/'images'/item['image']
        if not path.is_file() or digest(path)!=item['image_sha256']:raise ValueError(f'Image missing or hash mismatch: {path}')
    stream=io.StringIO(newline='');writer=csv.DictWriter(stream,fieldnames=['image','qw','qx','qy','qz','sigma_degrees'],lineterminator='\n');writer.writeheader();writer.writerows(priors);csv_text=stream.getvalue()
    provenance={'convention':'Hamilton quaternion wxyz, world_from_camera; fused world_from_body @ BODY_FROM_CV @ transpose(camera_from_rig rotation)','body_from_cv':BODY_FROM_CV.tolist(),'sigma_degrees':a.sigma_degrees,'sigma_basis':'assumed one-sigma weight, not a measured uncertainty','heading':'preserved in fused body orientation; no yaw cancellation','source_hashes':{'dataset_manifest':digest(manifest),'rig_config':digest(rig_path),'fused_csv':digest(fused),'export_script':digest(Path(__file__))},'source_paths':{'dataset_manifest':str(manifest),'rig_config':str(rig_path),'fused_csv':str(fused)},'output_csv_sha256':hashlib.sha256(csv_text.encode()).hexdigest(),'images':images}
    with a.output_csv.open('x',newline='') as f:f.write(csv_text)
    with a.provenance_json.open('x') as f:json.dump(provenance,f,indent=2,allow_nan=False);f.write('\n')
if __name__=='__main__':main()
