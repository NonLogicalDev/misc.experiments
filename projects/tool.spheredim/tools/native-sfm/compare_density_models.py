#!/usr/bin/env python3
"""Compare shared rig poses and common training-observation residuals."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
import numpy as np
import compare_rigs as c


def read_exact(f,n):
    b=f.read(n)
    if len(b)!=n:raise ValueError('Truncated COLMAP file')
    return b


def points(path):
    result={}
    with path.open('rb') as f:
        n,=struct.unpack('<Q',read_exact(f,8))
        for _ in range(n):
            row=struct.unpack('<Q3d3BdQ',read_exact(f,51));key=row[0]
            if key in result:raise ValueError('Duplicate point id')
            result[key]=np.asarray(row[1:4],dtype=float);read_exact(f,row[-1]*8)
        if f.read(1):raise ValueError('Trailing point bytes')
    return result


def observations(path):
    result={}
    with path.open('rb') as f:
        n,=struct.unpack('<Q',read_exact(f,8))
        for _ in range(n):
            row=struct.unpack('<i7di',read_exact(f,64));name=bytearray()
            while (ch:=read_exact(f,1))!=b'\0':
                name+=ch
                if len(name)>65536:raise ValueError('Invalid image name')
            name=name.decode();count,=struct.unpack('<Q',read_exact(f,8));obs={};duplicates=set()
            for _ in range(count):
                x,y,pid=struct.unpack('<ddq',read_exact(f,24));key=(x,y)
                if pid<0:continue
                if key in obs:duplicates.add(key)
                obs[key]=pid
            for key in duplicates:del obs[key]
            if name in result:raise ValueError('Duplicate image name')
            result[name]=obs
        if f.read(1):raise ValueError('Trailing image bytes')
    return result


def summary(values):
    if not values:return {'count':0}
    a=np.asarray(values,dtype=float)
    return {'count':len(a),'median':float(np.median(a)),'p90':float(np.percentile(a,90)),'p95':float(np.percentile(a,95)),'max':float(a.max())}


def rotation_alignment(a,b,names):
    # R is world-to-camera. A maps model B world axes into model A world axes.
    m=sum((a[n][0].T@b[n][0] for n in names),np.zeros((3,3)))
    u,_,vt=np.linalg.svd(m);d=np.eye(3);d[-1,-1]=np.linalg.det(u@vt)
    return u@d@vt


def residual(name,xy,pid,poses,pts,width,height):
    if pid not in pts:raise ValueError(f'Missing 3D point {pid}')
    R,C=poses[name];v=R@(pts[pid]-C);norm=np.linalg.norm(v)
    if not np.isfinite(norm) or norm<1e-12:raise ValueError('Invalid 3D observation')
    ray=c.ray(*xy,width,height);return math.acos(float(np.clip(np.dot(ray,v/norm),-1,1)))*width/(2*math.pi)


def compare(model_a,model_b,manifest,width=1024,height=512):
    a=c.read_poses(model_a);b=c.read_poses(model_b);obs_a=observations(model_a/'images.bin');obs_b=observations(model_b/'images.bin');pa=points(model_a/'points3D.bin');pb=points(model_b/'points3D.bin')
    frames=[x['source_frame'] for x in json.loads(manifest.read_text())['frames']];names=[f'cam{j}/frame_{i:06d}.png' for i in frames for j in (0,1)]
    if len(names)!=len(set(names)) or set(names)-a.keys() or set(names)-b.keys():raise ValueError('Shared cameras missing or duplicated')
    primary=[n for n in names if n.startswith('cam0/')];A=rotation_alignment(a,b,primary);angles=[];per=[];all_a=[];all_b=[]
    for n in names:
        D=a[n][0]@A@b[n][0].T;ang=math.degrees(math.acos(float(np.clip((np.trace(D)-1)/2,-1,1))));angles.append(ang)
        common=obs_a[n].keys() & obs_b[n].keys();ra=[residual(n,xy,obs_a[n][xy],a,pa,width,height) for xy in common];rb=[residual(n,xy,obs_b[n][xy],b,pb,width,height) for xy in common];all_a.extend(ra);all_b.extend(rb)
        per.append({'image':n,'orientation_disagreement_deg':ang,'common_observations':len(common),'a_reprojection_erp_equivalent_px':summary(ra),'b_reprojection_erp_equivalent_px':summary(rb)})
    return {'method':'A single fitted world rotation on shared cam0 orientations aligns B to A; orientation differences are cross-model agreement, not truth. Reprojection uses exactly matching source keypoint coordinates in both images but each model has its own associated 3D point and fit. Observations were used in SfM and are not held out. Spherical angular errors converted to width/(2*pi) pixels; no 3D or metric accuracy claim.',
            'shared_images':len(names),'world_a_from_world_b_rotation':A.tolist(),'orientation_disagreement_deg':summary(angles),'common_training_observations':len(all_a),'a_reprojection_erp_equivalent_px':summary(all_a),'b_reprojection_erp_equivalent_px':summary(all_b),'per_image':per}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('baseline_model',type=Path);p.add_argument('dense_model',type=Path);p.add_argument('baseline_manifest',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
    if a.output.exists():raise FileExistsError(a.output)
    result=compare(a.baseline_model,a.dense_model,a.baseline_manifest)
    def digest(path):
        with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
    result['sha256']={'baseline_images':digest(a.baseline_model/'images.bin'),'baseline_points':digest(a.baseline_model/'points3D.bin'),'dense_images':digest(a.dense_model/'images.bin'),'dense_points':digest(a.dense_model/'points3D.bin'),'baseline_manifest':digest(a.baseline_manifest),'script':digest(Path(__file__))}
    with a.output.open('x') as f:json.dump(result,f,indent=2,allow_nan=False);f.write('\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ('per_image','world_a_from_world_b_rotation')},indent=2))
if __name__=='__main__':main()
