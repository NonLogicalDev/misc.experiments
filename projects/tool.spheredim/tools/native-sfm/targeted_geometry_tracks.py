#!/usr/bin/env python3
"""Compare two spherical pose models on frozen source feature tracks in selected regions."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

import cv2
import numpy as np
import compare_density_models as modelio
import compare_rigs as rig
import prepare_splat as splat

REGIONS=(
    ('poster_1365','cam1/frame_001365.png',(750,190,135,145)),
    ('clock_1365','cam1/frame_001365.png',(817,375,90,55)),
    ('poster_1440','cam0/frame_001440.png',(635,90,90,80)),
    ('clock_1440','cam0/frame_001440.png',(605,180,45,60)),
    ('blinds_1440','cam0/frame_001440.png',(320,290,320,155)),
)


def predicted_xy(vector,width=1024,height=512):
    unit=np.asarray(vector,dtype=float);norm=np.linalg.norm(unit)
    if not np.isfinite(norm) or norm<1e-12:raise ValueError('Invalid predicted bearing')
    unit/=norm;theta=np.arctan2(unit[0],unit[2]);phi=np.arcsin(np.clip(-unit[1],-1,1))
    return np.array([(theta/(2*np.pi)+.5)*width,(.5-phi/np.pi)*height])


def target_residual(point,pose,xy):
    rotation,center=pose;pred=predicted_xy(rotation@(point-center));delta=pred-np.asarray(xy)
    delta[0]=(delta[0]+512)%1024-512
    measured=rig.ray(*xy,1024,512);predicted=rotation@(point-center);predicted/=np.linalg.norm(predicted)
    angular=float(np.arccos(np.clip(measured@predicted,-1,1))*1024/(2*np.pi))
    return {'angular_erp_equivalent_px':angular,'horizontal_px':float(delta[0]),'vertical_px':float(delta[1])}


def calculate_track(reference,neighbors,poses):
    def ray_observation(obs):
        name,xy=obs;rotation,center=poses[name]
        return center,rotation.T@rig.ray(*xy,1024,512)
    point,reason=rig.triangulate(ray_observation(neighbors[0]),ray_observation(neighbors[1]),min_angle=.2)
    if reason:return None,reason
    try:return target_residual(point,poses[reference[0]],reference[1]),None
    except ValueError:return None,'invalid_prediction'


def stats(rows,key):
    values=[r[key] for r in rows]
    if not values:return None
    return {'count':len(values),'median':float(np.median(values)),'p10':float(np.percentile(values,10)),'p90':float(np.percentile(values,90)),'max_abs':float(np.max(np.abs(values)))}


def run(model_a,model_b,prepared,output):
    model_a,model_b,prepared=(Path(p).resolve(strict=True) for p in (model_a,model_b,prepared));output=Path(output).resolve()
    if output.exists():raise FileExistsError(output)
    manifest=json.loads((prepared/'manifest.json').read_text());source=Path(manifest['dataset']).resolve(strict=True);source_manifest=source/'manifest.json'
    if splat.digest(source_manifest)!=manifest['source_manifest_sha256']:raise ValueError('Source manifest hash mismatch')
    source_by={x['source_frame']:x for x in json.loads(source_manifest.read_text())['frames']}
    byname={x['source_name']:x for x in manifest['frames']};poses=[rig.read_poses(model_a),rig.read_poses(model_b)];obs=modelio.observations(model_a/'images.bin')
    if set(byname)-obs.keys() or any(set(byname)-p.keys() for p in poses):raise ValueError('Missing source observations or model poses')
    mask_cache={}
    def valid(name,xy):
        if name not in mask_cache:
            r=byname[name];path=prepared/'masks'/r['name'];expected=source_by[r['source_frame']]['lenses'][r['lens']]['mask_sha256']
            if splat.digest(path)!=expected:raise ValueError('Source mask hash mismatch')
            mask=cv2.imread(str(path),cv2.IMREAD_GRAYSCALE)
            if mask is None or mask.shape!=(512,1024):raise ValueError('Invalid source mask')
            mask_cache[name]=mask
        x,y=map(lambda v:int(round(v)),xy)
        return 0<=x<1024 and 0<=y<512 and mask_cache[name][y,x]==255
    needed=set();regions=[]
    for label,name,(x,y,w,h) in REGIONS:
        rows=[(xy,pid) for xy,pid in obs[name].items() if x<=xy[0]<x+w and y<=xy[1]<y+h and valid(name,xy)]
        needed.update(pid for xy,pid in rows);regions.append((label,name,(x,y,w,h),rows))
    tracks=defaultdict(list)
    for name,points in obs.items():
        frame=byname[name]['source_frame']
        if not 1300<=frame<=1500:continue
        for xy,pid in points.items():
            if pid in needed and valid(name,xy):tracks[pid].append((frame,name,xy))
    results=[]
    for label,name,rect,rows in regions:
        ref_frame=byname[name]['source_frame'];details=[];fail=Counter()
        for xy,pid in rows:
            choices=[o for o in tracks[pid] if o[0]!=ref_frame]
            times=sorted(set(o[0] for o in choices))
            if len(times)<2:fail['insufficient_neighbor_timestamps']+=1;continue
            endpoints=[]
            for t in (times[0],times[-1]):
                options=sorted((o for o in choices if o[0]==t),key=lambda o:(o[1].split('/')[0]!=name.split('/')[0],o[1]))
                endpoints.append((options[0][1],options[0][2]))
            outcomes=[calculate_track((name,xy),endpoints,p) for p in poses]
            if any(reason for _,reason in outcomes):
                for i,(_,reason) in enumerate(outcomes):
                    if reason:fail[('baseline_' if i==0 else 'native_')+reason]+=1
                continue
            details.append({'point_id':pid,'reference_xy':list(xy),'neighbor_names':[e[0] for e in endpoints],'neighbor_xy':[list(e[1]) for e in endpoints],'baseline':outcomes[0][0],'native_2048':outcomes[1][0]})
        metrics={}
        for key in ('baseline','native_2048'):
            values=[d[key] for d in details]
            metrics[key]={field:stats(values,field) for field in ('angular_erp_equivalent_px','horizontal_px','vertical_px')}
        results.append({'region':label,'reference':name,'rect_xywh':rect,'mask_valid_source_features':len(rows),'shared_valid_tracks':len(details),'excluded':dict(fail),'metrics':metrics,'tracks':details})
    data={'method':'Frozen original-model SIFT associations and 1024 source coordinates; exact same source observations and endpoints in both models. Reference timestamp withheld from each local triangulation, but input feature associations and poses derive from these related SfM data and orientation priors. Not independent pose truth. Values describe valid feature tracks only, not texture without matched keypoints; no render alignment. Horizontal residual wraps at ERP seam, vertical is image y. Neighbor timestamps limited to 1300..1500. Separate failure counts may overlap for a track.','source_prepared':str(prepared),'source_manifest_sha256':splat.digest(source_manifest),'prepared_manifest_sha256':splat.digest(prepared/'manifest.json'),'models':[{'path':str(p),'images_sha256':splat.digest(p/'images.bin'),'points_sha256':splat.digest(p/'points3D.bin')} for p in (model_a,model_b)],'script_sha256':splat.digest(Path(__file__)),'regions':results}
    raw=(json.dumps(data,indent=2,allow_nan=False)+'\n').encode()
    if len(raw)>5*1024**2:raise ValueError('Report exceeds 5 MiB')
    with output.open('xb') as f:f.write(raw)
    return data


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('baseline_model',type=Path);p.add_argument('native_model',type=Path);p.add_argument('prepared',type=Path);p.add_argument('output',type=Path);a=p.parse_args();d=run(a.baseline_model,a.native_model,a.prepared,a.output);print(json.dumps([{k:v for k,v in r.items() if k!='tracks'} for r in d['regions']],indent=2))


if __name__=='__main__':main()
