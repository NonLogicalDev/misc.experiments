#!/usr/bin/env python3
"""Compare original sparse landmark reprojections to their fixed-plane projections."""
import argparse
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np
import compare_density_models as io
import compare_rigs as rig
from pose_sensitivity import validate_original_cameras


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for data in iter(lambda:f.read(1048576),b''):h.update(data)
    return h.hexdigest()


def residual(point,pose,xy):
    R,C=pose;v=R@(point-C);norm=np.linalg.norm(v)
    if not np.isfinite(norm) or norm<1e-12:raise ValueError('Invalid reprojected point')
    lon=np.arctan2(v[0],v[2]);lat=np.arctan2(v[1],np.hypot(v[0],v[2]));obs_lon=(xy[0]/1024-.5)*2*np.pi;obs_lat=(xy[1]/512-.5)*np.pi
    dlon=(lon-obs_lon+np.pi)%(2*np.pi)-np.pi
    # Both stored features and projection use original 1024 SfM convention;
    # multiplying by two gives native-2048-equivalent angular-pixel units.
    return np.array([dlon*np.cos(obs_lat),lat-obs_lat])*2048/(2*np.pi)


def summary(rows,key):
    if not rows:return {'count':0}
    v=np.array([row[key] for row in rows]);mag=np.linalg.norm(v,axis=1)
    return {'count':len(rows),'angular_magnitude_native_px_p50_p90':np.percentile(mag,[50,90]).tolist(),'mean_east_down_native_px':v.mean(axis=0).tolist()}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('model',type=Path);p.add_argument('prepared',type=Path);p.add_argument('plane_report',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
    if a.output.exists():raise FileExistsError(a.output)
    validate_original_cameras(a.model/'cameras.bin');plane=json.loads(a.plane_report.read_text());normal=np.asarray(plane['plan']['plane_normal']);d=plane['plan']['plane_d']
    if not np.isclose(np.linalg.norm(normal),1,atol=1e-8):raise ValueError('Plane normal must be unit length')
    for name in ('cameras.bin','images.bin','points3D.bin'):
        if sha(a.model/name)!=plane['model_sha256'][name]:raise ValueError(f'Plane/model mismatch: {name}')
    modelobs=io.observations(a.model/'images.bin');points=io.points(a.model/'points3D.bin');poses=rig.read_binary_poses(a.model/'images.bin');manifest=json.loads((a.prepared/'manifest.json').read_text());by={r['source_name']:r for r in manifest['frames']};landmarks={r['point_id']:r for r in plane['plane_landmarks']};per={};matched={}
    for frame in (1440,1495,1500,1505,1560):
        name=f'cam0/frame_{frame:06}.png';record=by[name];maskpath=a.prepared/'masks'/record['name'];mask=cv2.imread(str(maskpath),0)
        if mask is None or mask.shape!=(1024,2048):raise ValueError('Invalid native mask')
        obs={pid:xy for xy,pid in modelobs[name].items() if pid in landmarks};rows=[];masked=0
        for pid,xy in obs.items():
            x,y=np.rint(np.array(xy)*2).astype(int)
            if x<0 or x>=2048 or y<0 or y>=1024 or mask[y,x]!=255:masked+=1;continue
            point=points[pid];projected=point-(point@normal+d)*normal
            rows.append({'point_id':int(pid),'plane_fit_inlier':landmarks[pid]['inlier'],'feature_xy_original_1024':list(xy),'original_east_down_native_px':residual(point,poses[name],xy).tolist(),'plane_east_down_native_px':residual(projected,poses[name],xy).tolist()})
        matched[name]={r['point_id'] for r in rows};inliers=[r for r in rows if r['plane_fit_inlier']]
        per[name]={'split':record['split'],'observed_ids_before_mask':len(obs),'masked_or_outside':masked,'training_plane_inlier_landmarks':{'original':summary(inliers,'original_east_down_native_px'),'plane':summary(inliers,'plane_east_down_native_px')},'all_supported_landmarks':{'original':summary(rows,'original_east_down_native_px'),'plane':summary(rows,'plane_east_down_native_px')},'mask_sha256':sha(maskpath),'observations':rows}
    common=set.intersection(*matched.values())
    report={'method':'Original 1024 SfM feature coordinates and camera poses, scaled to 2048-equivalent angular pixel units. Predicted and observed bearings use the same stored SfM coordinate convention (original run records SS_SFM_PIXEL_CENTER=0); no +0.5 applied. No native-2048 features, pixel remapping, pose/plane fit or image alignment. Compare original landmark with its orthogonal projection onto the previously fixed plane. Original model used all views including splat holdouts; matching and residuals are in-sample, not independent truth. Mask validity does not establish physical visibility.','plane_report_sha256':sha(a.plane_report),'model_sha256':{name:sha(a.model/name) for name in ('cameras.bin','images.bin','points3D.bin')},'prepared_manifest_sha256':sha(a.prepared/'manifest.json'),'script_sha256':sha(Path(__file__)),'matched_in_all_five_frames':len(common),'matched_in_all_five_ids':sorted(common),'frames':per}
    text=json.dumps(report,indent=2,allow_nan=False)+'\n'
    if len(text.encode())>1000000:raise ValueError('Report exceeds 1 MB')
    a.output.write_text(text);print(json.dumps({'matched_in_all_five':len(common),'frames':{k:{x:v[x] for x in ('observed_ids_before_mask','masked_or_outside','training_plane_inlier_landmarks','all_supported_landmarks')} for k,v in per.items()}},indent=2))
if __name__=='__main__':main()
