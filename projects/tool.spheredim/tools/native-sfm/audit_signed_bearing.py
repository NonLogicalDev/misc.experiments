#!/usr/bin/env python3
"""Summarize signed training-track reprojection residuals in native ERP views."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import time
import cv2
import numpy as np
import compare_density_models as io
from audit_seed_gauge import read_erp_cameras
import compare_rigs as rig
from prepare_rig import BODY_FROM_CV


def signed_residual(points,rotation,center,xy,width,height):
    v=(points-center)@rotation.T;depth=np.linalg.norm(v,axis=1)
    lon=np.arctan2(v[:,0],v[:,2]);lat=np.arctan2(v[:,1],np.hypot(v[:,0],v[:,2]))
    src_lon=(xy[:,0]/width-.5)*2*np.pi;src_lat=(xy[:,1]/height-.5)*np.pi
    delta_lon=(lon-src_lon+np.pi)%(2*np.pi)-np.pi
    # Tangent-plane east and down in units of 1024-ERP-equivalent pixels.
    return np.column_stack((delta_lon*np.cos(src_lat),lat-src_lat))*1024/(2*np.pi),depth


def summarize(v):
    if len(v)==0:return {'count':0}
    mag=np.linalg.norm(v,axis=1);mean=v.mean(axis=0);return {'count':len(v),'mean_east_down_px':mean.tolist(),'median_east_down_px':np.median(v,axis=0).tolist(),'magnitude_p50_p90_px':np.percentile(mag,[50,90]).tolist(),'directional_coherence':float(np.linalg.norm(mean)/mag.mean()) if mag.mean()>0 else None}


def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()


def validate_native_cameras(path):
    cameras = read_erp_cameras(path)
    if any(values[:2] != (2048, 1024) or not np.allclose(values[2:], [2048, 1024], rtol=0, atol=1e-9) for values in cameras.values()):
        raise ValueError('Expected full-sphere 2048x1024 ERP cameras')
    return cameras


def training_frames(manifest):
    frames = {}
    for row in manifest['frames']:
        if row['split'] != 'train':
            continue
        name = row['source_name']
        if name in frames:
            raise ValueError(f'Duplicate training source name: {name}')
        frames[name] = row
    return frames


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('model',type=Path);p.add_argument('prepared',type=Path);p.add_argument('tracks',type=Path);p.add_argument('calibration',type=Path);p.add_argument('output',type=Path);p.add_argument('--timeout',type=int,default=160);a=p.parse_args();start=time.monotonic()
    if a.output.exists():raise FileExistsError(a.output)
    man = json.loads((a.prepared / 'manifest.json').read_text())
    frames = training_frames(man)
    cameras = validate_native_cameras(a.model / 'cameras.bin')
    if any(int(row['colmap_camera_id']) not in cameras for row in frames.values()):
        raise ValueError('Training image references unknown camera')
    poses = rig.read_binary_poses(a.model / 'images.bin')
    observations = io.observations(a.model / 'images.bin')
    points = io.points(a.model / 'points3D.bin')
    cal = json.loads(a.calibration.read_text())
    source_report=json.loads((a.tracks.parent/'report.json').read_text())
    if source_report['point_tracks_sha256']!=sha(a.tracks) or source_report['inputs'].get(str(a.model/'images.bin'))!=sha(a.model/'images.bin') or source_report['inputs'].get(str(a.model/'points3D.bin'))!=sha(a.model/'points3D.bin'):raise ValueError('Track provenance does not match model')
    with gzip.open(a.tracks,'rt') as f:rows=json.load(f)['native_own']
    track = {r[0]: (r[2], r[5]) for r in rows}
    data = {lens: [] for lens in ('cam0', 'cam1')}
    mask_hashes = {}
    axes={}
    for lens in (0,1):
        q=cal['lenses'][lens]['orientation'];R=rig.rotation([q['w'],q['x'],q['y'],q['z']]);axes[f'cam{lens}']=BODY_FROM_CV.T@R.T@np.array([0.,0.,1.])
    for name,row in frames.items():
        if time.monotonic()-start>a.timeout:raise TimeoutError('Deadline exceeded')
        mask_path = a.prepared / 'masks' / row['name']
        mask_hashes[row['name']] = sha(mask_path)
        m = cv2.imread(str(mask_path), 0)
        if m is None or m.shape != (1024, 2048):
            raise ValueError(f'Invalid native mask: {mask_path}')
        entries=observations[name];xy=np.array(list(entries),float);pid=np.array(list(entries.values()),dtype=np.int64)
        if not len(xy):continue
        ix=np.rint(xy[:,0]).astype(int);iy=np.rint(xy[:,1]).astype(int);inside=(ix>=0)&(ix<2048)&(iy>=0)&(iy<1024);valid=np.zeros(len(xy),bool);valid[inside]=m[iy[inside],ix[inside]]==255;idx=np.flatnonzero(valid);xy=xy[idx];pid=pid[idx]
        present=np.array([int(x) in points and int(x) in track for x in pid]);xy=xy[present];pid=pid[present]
        if not len(xy):continue
        xyz=np.array([points[int(x)] for x in pid]);R,C=poses[name];res,depth=signed_residual(xyz,R,C,xy,2048,1024)
        lon=(xy[:,0]/2048-.5)*2*np.pi;lat=(xy[:,1]/1024-.5)*np.pi;ray=np.column_stack((np.sin(lon)*np.cos(lat),np.sin(lat),np.cos(lon)*np.cos(lat)))
        axis=axes[row['lens']];dot=ray@axis;radius=np.degrees(np.arccos(np.clip(dot,-1,1)))
        outward=dot[:,None]*ray-axis;norm=np.linalg.norm(outward,axis=1);outward/=np.maximum(norm[:,None],1e-12)
        east=np.column_stack((np.cos(lon),np.zeros(len(lon)),-np.sin(lon)));down=np.column_stack((-np.sin(lon)*np.sin(lat),np.cos(lat),-np.cos(lon)*np.sin(lat)))
        radial=res[:,0]*np.sum(outward*east,axis=1)+res[:,1]*np.sum(outward*down,axis=1);radial[norm<1e-10]=np.nan
        par=np.array([track[int(x)][1] if track[int(x)][1] is not None else np.nan for x in pid]);length=np.array([track[int(x)][0] for x in pid]);tiles=(np.minimum((xy[:,0]/256).astype(int),7)+8*np.minimum((xy[:,1]/256).astype(int),3))
        data[row['lens']].append((res,depth,radius,par,length,tiles,radial))
    result={}
    for lens,parts in data.items():
        if not parts:raise ValueError('No valid observations for lens')
        res,depth,radius,par,length,tiles,radial=[np.concatenate([part[i] for part in parts]) for i in range(7)];out={'overall':summarize(res),'radial_bins_degrees':{},'tiles_8x4':{},'track_length_distinct_timestamps':{},'max_parallax_degrees':{},'depth_quantiles_model_units':{}}
        for low,high in [(0,30),(30,60),(60,90),(90,120),(120,180.0001)]:
            select=(radius>=low)&(radius<high);r=radial[select];r=r[np.isfinite(r)];stats=summarize(res[select]);stats['mean_outward_px']=float(np.mean(r)) if len(r) else None;stats['median_outward_px']=float(np.median(r)) if len(r) else None;out['radial_bins_degrees'][f'{low}-{high:g}']=stats
        for i in range(32):out['tiles_8x4'][f'{i%8},{i//8}']=summarize(res[tiles==i])
        for low,high in [(0,3),(3,5),(5,10),(10,100000)]:out['track_length_distinct_timestamps'][f'{low}-{high}']=summarize(res[(length>=low)&(length<high)])
        for low,high in [(0,2),(2,5),(5,15),(15,180.001)]:out['max_parallax_degrees'][f'{low}-{high:g}']=summarize(res[(par>=low)&(par<high)])
        bounds=np.quantile(depth,[0,.25,.5,.75,1]);out['depth_quantile_bounds_model_units']=bounds.tolist()
        for i in range(4):out['depth_quantiles_model_units'][str(i)]=summarize(res[(depth>=bounds[i])&((depth<bounds[i+1]) if i<3 else (depth<=bounds[i+1]))])
        result[lens]=out
    report={'method':'Signed prediction minus observation in local ERP east/down tangent components, in 1024-ERP-equivalent angular pixels; no pose fitting or image alignment. Training observations of the same model are in-sample, repeated tracks/frames are correlated, and fitted SfM can absorb calibration errors. Mean-direction coherence is magnitude(mean vector)/mean magnitude; small coherence does not establish accuracy. Radial bins are nominal angles to embedded calibration axes, not independently verified source-coordinate radii; see axis caveat.','track_caveat':'Track timestamp counts and parallax come from the paired prior audit using conservative 1024 masks; residuals here use native 2048 masks.','axis_caveat':'Nominal exporter lens axis = inverse recorded lens orientation applied to local +Z, transformed through BODY_FROM_CV. Source-coordinate per-pixel provenance and applied lens1 alignment are not recorded in these manifests; radial interpretation is provisional, especially cam1.','nominal_axis_cv':{k:v.tolist() for k,v in axes.items()},'training_mask_sha256':mask_hashes,'inputs':{str(x):sha(x) for x in (a.model/'cameras.bin',a.model/'images.bin',a.model/'points3D.bin',a.prepared/'manifest.json',a.tracks,a.calibration,Path(__file__))},'results':result,'elapsed_seconds':time.monotonic()-start}
    a.output.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n');print(json.dumps({k:v['overall'] for k,v in result.items()},indent=2))
if __name__=='__main__':main()
