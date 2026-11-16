#!/usr/bin/env python3
"""Audit native SfM points in the original camera gauge, using training observations."""
import argparse
from collections import defaultdict
import gzip
import hashlib
import json
import struct
from pathlib import Path
import time

import cv2
import numpy as np
import compare_density_models as modelio
import compare_rigs as rig



def read_erp_cameras(path):
    """Read the two-parameter COLMAP ERP camera records used by this audit."""
    with path.open('rb') as f:
        data=f.read(8)
        if len(data)!=8:raise ValueError('Truncated camera header')
        count,=struct.unpack('<Q',data); cameras={}
        for _ in range(count):
            data=f.read(40)
            if len(data)!=40:raise ValueError('Truncated ERP camera')
            camera_id,model,width,height,a,b=struct.unpack('<iiQQdd',data)
            if model!=17 or camera_id in cameras or not np.isfinite([a,b]).all():raise ValueError('Expected unique finite ERP cameras (model 17)')
            cameras[camera_id]=(width,height,a,b)
        if f.read(1):raise ValueError('Unexpected camera data')
    if not cameras:raise ValueError('No cameras')
    return cameras


def validate_2x_cameras(original, native):
    if original.keys()!=native.keys():raise ValueError('Camera IDs differ')
    for camera_id,low in original.items():
        high=native[camera_id]
        if low[:2]!=(1024,512) or high[:2]!=(2048,1024) or not np.allclose(high[2:],np.asarray(low[2:])*2,rtol=0,atol=1e-9):
            raise ValueError('Expected matching 1024/2048 ERP camera parameters')
        if not np.allclose(low[2:],[1024,512],rtol=0,atol=1e-9):raise ValueError('Expected full-sphere ERP parameters')


def fit_similarity(source, target):
    source=np.asarray(source,float);target=np.asarray(target,float)
    if source.shape!=target.shape or source.ndim!=2 or source.shape[1]!=3 or len(source)<3:raise ValueError('Need at least three paired 3D centers')
    a=source-source.mean(axis=0);b=target-target.mean(axis=0);var=np.sum(a*a)/len(a)
    if var<1e-15 or np.linalg.matrix_rank(a)<2:raise ValueError('Degenerate camera centers')
    u,s,vt=np.linalg.svd(b.T@a/len(a));sign=np.ones(3);sign[-1]=np.linalg.det(u@vt);rotation=u@np.diag(sign)@vt;scale=float(np.dot(s,sign)/var)
    if scale<=0:raise ValueError('Invalid similarity scale')
    translation=target.mean(axis=0)-scale*rotation@source.mean(axis=0)
    return scale,rotation,translation


def angular_errors(points,rotation,center,xy,width):
    vectors=(points-center)@rotation.T;length=np.linalg.norm(vectors,axis=-1)
    valid=np.isfinite(vectors).all(axis=-1)&(length>1e-12)
    lon=(xy[:,0]/width-.5)*(2*np.pi);lat=(xy[:,1]/(width/2)-.5)*np.pi
    rays=np.column_stack((np.sin(lon)*np.cos(lat),np.sin(lat),np.cos(lon)*np.cos(lat)))
    dot=np.sum(vectors*rays,axis=-1)/np.maximum(length,1e-12)
    error=np.arccos(np.clip(dot,-1,1))*1024/(2*np.pi)
    error[~valid]=np.inf
    return error


def parallax(point, centers):
    vectors=np.asarray(centers)-point;length=np.linalg.norm(vectors,axis=1)
    if len(vectors)<2 or np.any(length<1e-12):return 0.
    dirs=vectors/length[:,None];minimum=np.clip(np.min(dirs@dirs.T),-1,1)
    return float(np.degrees(np.arccos(minimum)))


def point_gate(errors,timestamps,angle):
    if len(set(timestamps))<3:return False
    return bool(np.median(errors)<=1 and np.percentile(errors,90)<=2 and angle>=2.)


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for part in iter(lambda:f.read(1048576),b''):h.update(part)
    return h.hexdigest()


def audit(model, poses, frames, prepared, scale, rotation, translation, width, timeout, started):
    points=modelio.points(model/'points3D.bin');obs=modelio.observations(model/'images.bin')
    ids=np.fromiter(points.keys(),dtype=np.int64); xyz=np.array(list(points.values()));mapped=scale*(xyz@rotation.T)+translation;lookup={int(pid):i for i,pid in enumerate(ids)}
    tracks=defaultdict(list);regions={'poster_1365':('cam1/frame_001365.png',(750,190,135,145)), 'clock_1365':('cam1/frame_001365.png',(817,375,90,55)), 'blinds_1435':('cam0/frame_001435.png',(400,330,140,35))};region_ids={k:set() for k in regions}
    invalid_mask=0
    for name,row in frames.items():
        if time.monotonic()-started>timeout:raise TimeoutError('Audit exceeded CPU deadline')
        if row['split']!='train':continue
        mask=cv2.imread(str(prepared/'masks'/row['name']),0)
        if mask is None or mask.shape!=(512,1024):raise ValueError(f'Invalid mask {name}')
        entries=obs[name]
        if not entries:continue
        xy=np.array(list(entries),dtype=float);pids=np.array(list(entries.values()),dtype=np.int64);idx=np.array([lookup.get(int(p),-1) for p in pids]);pos=xy*(1024/width)
        mx=np.rint(pos[:,0]).astype(int);my=np.rint(pos[:,1]).astype(int);inside=(mx>=0)&(mx<1024)&(my>=0)&(my<512)&(idx>=0);valid=np.zeros(len(xy),bool);valid[inside]=mask[my[inside],mx[inside]]==255;invalid_mask+=int((~valid).sum())
        inds=np.flatnonzero(valid)
        if not len(inds):continue
        R,C=poses[name];errs=angular_errors(mapped[idx[inds]],R,C,xy[inds],width)
        for j,e in zip(inds,errs):
            if np.isfinite(e):tracks[int(pids[j])].append((float(e),row['source_frame'],C))
        for label,(wanted,(x,y,w,h)) in regions.items():
            if name==wanted:
                take=valid&(pos[:,0]>=x)&(pos[:,0]<x+w)&(pos[:,1]>=y)&(pos[:,1]<y+h)
                region_ids[label].update(map(int,pids[take]))
    rows=[];accepted=set();counts={'points_total':len(ids),'points_with_training_observations':len(tracks),'pass_three_timestamps':0,'pass_residuals':0,'pass_all':0,'pass_parallax_thresholds':{'0.2':0,'1':0,'2':0,'5':0},'invalid_mask_or_missing_point_observations':invalid_mask};all_med=[];all_p90=[];conditioning=[]
    for pid,values in tracks.items():
        if time.monotonic()-started>timeout:raise TimeoutError('Audit exceeded CPU deadline')
        errors=np.array([v[0] for v in values]);times=[v[1] for v in values];n=len(set(times));med=float(np.median(errors));p90=float(np.percentile(errors,90));angle=parallax(mapped[lookup[pid]],[v[2] for v in values]) if len(values)>=2 else None;passed=point_gate(errors,times,angle or 0.)
        if n>=3:
            counts['pass_three_timestamps']+=1;all_med.append(med);all_p90.append(p90)
            if med<=1 and p90<=2:
                counts['pass_residuals']+=1
                for threshold in (.2,1,2,5):
                    if angle>=threshold:counts['pass_parallax_thresholds'][str(threshold)]+=1
                if angle>0:conditioning.append(med*(360/1024)/angle)
        if passed:counts['pass_all']+=1;accepted.add(pid)
        rows.append([pid,len(values),n,round(med,6),round(p90,6),round(angle,6) if angle is not None else None,passed])
    counts['median_bearing_angle_over_parallax_p50_p90']=np.percentile(conditioning,[50,90]).tolist() if conditioning else None
    rows.extend([int(pid),0,0,None,None,None,False] for pid in ids if int(pid) not in tracks)
    counts['training_track_median_residual_median_p90']=np.percentile(all_med,[50,90]).tolist() if all_med else None
    counts['training_track_p90_residual_median_p90']=np.percentile(all_p90,[50,90]).tolist() if all_p90 else None
    by_id={r[0]:r for r in rows}
    def region_summary(label, ids):
        rr=[by_id[pid] for pid in ids if pid in by_id]
        insufficient=sum(r[2]<3 for r in rr); bad_residual=sum(r[2]>=3 and (r[3]>1 or r[4]>2) for r in rr); bad_parallax=sum(r[2]>=3 and r[3]<=1 and r[4]<=2 and r[5]<2 for r in rr); passed=sum(r[6] for r in rr)
        return {'training_view_name':regions[label][0],'rect_1024_xywh':regions[label][1],'observed_points':len(ids),'insufficient_timestamps':insufficient,'residual_failed':bad_residual,'parallax_failed':bad_parallax,'pass_all':passed}
    counts['regions']={k:region_summary(k,v) for k,v in region_ids.items()}
    return counts,rows


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('original',type=Path);p.add_argument('native',type=Path);p.add_argument('prepared',type=Path);p.add_argument('output',type=Path);p.add_argument('--timeout',type=int,default=170);a=p.parse_args();started=time.monotonic()
    if a.output.exists():raise FileExistsError(a.output)
    man=json.loads((a.prepared/'manifest.json').read_text());frames={r['source_name']:r for r in man['frames']}
    low_cameras=read_erp_cameras(a.original/'cameras.bin');high_cameras=read_erp_cameras(a.native/'cameras.bin');validate_2x_cameras(low_cameras,high_cameras)
    orig=rig.read_binary_poses(a.original/'images.bin');native=rig.read_binary_poses(a.native/'images.bin')
    if len(frames)!=824 or set(frames)!=set(orig) or set(frames)!=set(native):raise ValueError('Expected identical 824 camera names')
    mask_hashes={r['name']:digest(a.prepared/'masks'/r['name']) for r in frames.values() if r['split']=='train'}
    names=sorted(frames);src=np.array([native[n][1] for n in names]);dst=np.array([orig[n][1] for n in names]);s,R,t=fit_similarity(src,dst);dis=np.linalg.norm(s*(src@R.T)+t-dst,axis=1)
    angles=[]
    for name in names:
        delta=orig[name][0]@R@native[name][0].T
        angles.append(float(np.degrees(np.arccos(np.clip((np.trace(delta)-1)/2,-1,1)))))
    scores={};rows={}
    for name,model,width,sc,rot,tr,pose_set in [('original',a.original,1024,1,np.eye(3),np.zeros(3),orig),('native_own',a.native,2048,1,np.eye(3),np.zeros(3),native),('native_transferred',a.native,2048,s,R,t,orig)]:scores[name],rows[name]=audit(model,pose_set,frames,a.prepared,sc,rot,tr,width,a.timeout,started)
    own={r[0]:r for r in rows['native_own']};trans={r[0]:r for r in rows['native_transferred']}
    paired=[(own[k],trans[k]) for k in own.keys() & trans.keys() if own[k][2]>=3 and trans[k][2]>=3]
    pair_comparison={'points':len(paired),'own_median_residual_p50_p90':np.percentile([x[0][3] for x in paired],[50,90]).tolist() if paired else None,'transferred_median_residual_p50_p90':np.percentile([x[1][3] for x in paired],[50,90]).tolist() if paired else None,'median_residual_delta_p50_p90':np.percentile([x[1][3]-x[0][3] for x in paired],[50,90]).tolist() if paired else None}
    a.output.mkdir(parents=True);report={'method':'One proper Sim3 fitted to all 824 matched camera centers. Point support and angular residuals use only reviewed-mask-valid training observations; both source SfM models used heldout frames. Positive ray distance and angular bearing are used; a full ERP camera has no forward hemisphere. Parallax and residual gates do not establish depth truth. Region labels are training views.','similarity':{'scale':s,'rotation':R.tolist(),'translation':t.tolist(),'center_residual_p50_p90_p99':np.percentile(dis,[50,90,99]).tolist(),'orientation_difference_degrees_p50_p90_p99':np.percentile(angles,[50,90,99]).tolist()},'camera_models':{'original':low_cameras,'native':high_cameras},'criteria':{'min_training_timestamps':3,'median_residual_max_erp1024_px':1,'p90_residual_max_erp1024_px':2,'min_parallax_degrees':2},'results':scores,'paired_native_point_residual_comparison':pair_comparison,'training_mask_sha256':mask_hashes,'inputs':{str(path):digest(path) for path in (a.original/'cameras.bin',a.original/'images.bin',a.original/'points3D.bin',a.native/'cameras.bin',a.native/'images.bin',a.native/'points3D.bin',a.prepared/'manifest.json',Path(__file__))},'point_rows_schema':['point_id','training_observation_count','distinct_training_timestamps','median_error_erp1024_px','p90_error_erp1024_px','max_parallax_degrees','passes_gate'],'elapsed_seconds':time.monotonic()-started}
    with gzip.open(a.output/'point-tracks.json.gz','wt') as f:json.dump(rows,f,separators=(',',':'),allow_nan=False)
    if (a.output/'point-tracks.json.gz').stat().st_size>19_000_000:raise ValueError('Point report exceeds output budget')
    report['point_tracks_sha256']=digest(a.output/'point-tracks.json.gz');(a.output/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n');print(json.dumps({'similarity':report['similarity'],'results':scores,'paired_native_point_residual_comparison':pair_comparison,'elapsed_seconds':report['elapsed_seconds']},indent=2))
if __name__=='__main__':main()
