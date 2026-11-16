#!/usr/bin/env python3
"""Measured training-view poster plane sweep; accepted points remain provisional."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import time
import cv2
import numpy as np
from scipy.spatial import cKDTree
import compare_density_models as modelio
import compare_rigs as rig
from pose_sensitivity import validate_original_cameras
import temporal_depth_roi as erp

W,H=2048,1024
REFERENCE=1500
FIT_VIEWS=(1485,1490,1495)
RESERVED=1505
ROI=(450,440,250,250)


def fit_plane(points,threshold,seed=313):
    points=np.asarray(points,float);rng=np.random.default_rng(seed);best=None
    for _ in range(1000):
        a,b,c=points[rng.choice(len(points),3,replace=False)];n=np.cross(b-a,c-a);length=np.linalg.norm(n)
        if length<1e-10:continue
        n/=length;inliers=np.abs((points-a)@n)<=threshold
        if best is None or inliers.sum()>best.sum():best=inliers
    if best is None or best.sum()<6:raise ValueError('Insufficient planar support')
    center=points[best].mean(axis=0);_,_,vt=np.linalg.svd(points[best]-center,full_matrices=False);n=vt[-1]
    if n[np.argmax(np.abs(n))]<0:n=-n
    d=-float(n@center);res=points@n+d;inliers=np.abs(res)<=threshold
    return n,d,res,inliers


def intersect(rays,center,normal,offsets):
    """Intersect full source rays with parallel planes n·X + d = 0."""
    denom=rays@normal; distances=-(np.asarray(offsets)[:,None]+center@normal)/denom[None,:]
    valid=np.isfinite(distances)&(distances>0)&(np.abs(denom)[None,:]>1e-8)
    return center+distances[...,None]*rays[None,:,:],valid


def sample_bilinear(image,mask,x,y):
    h,w=mask.shape;x=np.asarray(x);y=np.asarray(y);ix=np.floor(x).astype(int)%w;iy=np.floor(y).astype(int);ok=(iy>=0)&(iy+1<h);y0=np.clip(iy,0,h-1);y1=np.clip(iy+1,0,h-1);x1=(ix+1)%w
    ok &= (mask[y0,ix]==255)&(mask[y0,x1]==255)&(mask[y1,ix]==255)&(mask[y1,x1]==255)
    fx=x-np.floor(x);fy=y-np.floor(y);top=image[y0,ix]*(1-fx)+image[y0,x1]*fx;bot=image[y1,ix]*(1-fx)+image[y1,x1]*fx
    return top*(1-fy)+bot*fy,ok


def separated_competitors(coords, k):
    dx=(coords[:,0]-coords[k,0]+W/2)%W-W/2
    return np.hypot(dx,coords[:,1]-coords[k,1])>=1.0



def competitor_margins(scores, coordinates, k):
    """Score the fixed hypothesis against each view's separated competitors."""
    margins=[]
    for row,coords in zip(scores,coordinates):
        alternatives=row[separated_competitors(coords,k) & np.isfinite(row)]
        margins.append(float(row[k]-alternatives.max()) if np.isfinite(row[k]) and len(alternatives) else None)
    return margins


def select(scores, coordinates, minimum=.8, margin=.03):
    """Require all views to distinguish the peak from separated projections."""
    scores=np.asarray(scores,float);valid=np.all(np.isfinite(scores),axis=0)
    if not valid.any():return None,'masked_or_unavailable'
    avg=np.where(valid,np.mean(scores,axis=0),-2);k=int(np.argmax(avg))
    if k in (0,len(avg)-1):return None,'depth_range_boundary'
    if np.min(scores[:,k])<minimum:return None,'low_match'
    for row,coords in zip(scores,coordinates):
        alternatives=row[separated_competitors(coords,k) & np.isfinite(row)]
        if not len(alternatives):return None,'depth_unresolved'
        if row[k]-alternatives.max()<margin:return None,'ambiguous_depth'
    return k,None


def patch_scores(reference,mask,pose,targets,x,y,plane_offsets,normal):
    R,C=pose;dx,dy=np.meshgrid(np.arange(-3,4),np.arange(-3,4));sx=(x+dx).ravel();sy=(y+dy).ravel();src,ok=sample_bilinear(reference,mask,sx,sy)
    if not ok.all():return None,'reference_mask'
    if np.std(src)<5:return None,'low_texture'
    source_rays=erp.rays(sx,sy,W,H)@R;world,positive=intersect(source_rays,C,normal,plane_offsets);a=src-src.mean();denom=np.sqrt(np.sum(a*a));scores=[];coordinates=[]
    for image,valid_mask,(Rt,Ct) in targets:
        xx,yy,_=erp.project(world,Rt,Ct,W,H);values,good=sample_bilinear(image,valid_mask,xx,yy);good &=positive
        means=values.mean(axis=1,keepdims=True);b=values-means;dn=np.sqrt(np.sum(b*b,axis=1))*denom
        row=np.divide(np.sum(b*a,axis=1),dn,out=np.full(len(plane_offsets),np.nan),where=dn>1e-9);row[~np.all(good,axis=1)]=np.nan;scores.append(row);coordinates.append(np.column_stack((xx[:,24],yy[:,24])))
    return (np.array(scores),np.array(coordinates)),None


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('prepared',type=Path);ap.add_argument('model',type=Path);ap.add_argument('output',type=Path);ap.add_argument('--describe',action='store_true');ap.add_argument('--fixed-plane-prior',action='store_true',help='Prepare a fixed-plane initialization hypothesis, not independent depths');ap.add_argument('--timeout',type=int,default=160);a=ap.parse_args();start=time.monotonic()
    if a.output.exists():raise FileExistsError(a.output)
    man=json.loads((a.prepared/'manifest.json').read_text());by={}
    for r in man['frames']:
        if r['lens']!='cam0':continue
        if r['source_frame'] in by:raise ValueError('Duplicate frame')
        by[r['source_frame']]=r
    ids=[REFERENCE,*FIT_VIEWS,RESERVED]
    if any(i not in by or by[i]['split']!='train' or by[i]['name'] in man['heldout_evaluation_order'] for i in ids):raise ValueError('Only distinct training captures allowed')
    validate_original_cameras(a.model/'cameras.bin')
    prepared_poses=rig.read_poses(a.prepared/'sparse/0')
    camera_lines=[line.split() for line in (a.prepared/'sparse/0/cameras.txt').read_text().splitlines() if line.strip() and not line.startswith('#')]
    if not camera_lines or any(len(r)!=6 or r[1]!='EQUIRECTANGULAR' or tuple(map(float,r[2:]))!=(2048.,1024.,2048.,1024.) for r in camera_lines):raise ValueError('Expected native full-sphere ERP cameras')
    poses=rig.read_binary_poses(a.model/'images.bin')
    for frame in ids:
        row=by[frame]; original=poses[row['source_name']]; prepared=prepared_poses[row['name']]
        if not all(np.allclose(x,y,rtol=0,atol=1e-8) for x,y in zip(original,prepared)):raise ValueError(f'Prepared pose differs from original: {frame}')
    obs=modelio.observations(a.model/'images.bin');points=modelio.points(a.model/'points3D.bin');ref=by[REFERENCE];source_name=ref['source_name'];R,C=poses[source_name];image=cv2.imread(str(a.prepared/'images'/ref['name']),0);mask=cv2.imread(str(a.prepared/'masks'/ref['name']),0)
    if image is None or mask is None or image.shape!=(H,W) or mask.shape!=(H,W):raise ValueError('Invalid reference')
    x,y,w,h=ROI;selected=[]
    for (xx,yy),pid in obs[source_name].items():
        u,v=2*xx,2*yy;ix=int(round(u));iy=int(round(v))
        if x<=u<x+w and y<=v<y+h and 0<=ix<W and 0<=iy<H and mask[iy,ix]==255 and pid in points:selected.append((u,v,pid))
    needed={p for _,_,p in selected};tracks=defaultdict(set)
    for row in man['frames']:
        if row['split']!='train' or not 1320<=row['source_frame']<=1530:continue
        mp=cv2.imread(str(a.prepared/'masks'/row['name']),0)
        for (xx,yy),pid in obs[row['source_name']].items():
            if pid not in needed:continue
            u,v=int(round(2*xx)),int(round(2*yy))
            if 0<=u<W and 0<=v<H and mp[v,u]==255:tracks[pid].add(row['source_frame'])
    selected=[r for r in selected if len(tracks[r[2]])>=3];P=np.array([points[p] for _,_,p in selected]);median=float(np.median(np.linalg.norm(P-C,axis=1)));normal,d,res,inliers=fit_plane(P,median*.005);signed=res[inliers]
    lo,hi=float(-signed.max()),float(-signed.min());offsets=None
    if not lo<0<hi:raise ValueError('Measured inlier offsets do not bracket plane')
    measured=np.array([[u,v] for (u,v,_),ok in zip(selected,inliers) if ok],np.float32);hull=cv2.convexHull(measured).reshape(-1,2)
    all_lo,all_hi=float(-res.max()),float(-res.min())
    offsets=np.unique(np.concatenate((d+np.linspace(all_lo,all_hi,65),[d])))
    ray=erp.rays(measured[:,0],measured[:,1],W,H)@R
    def range_displacements(bounds):
        world,positive=intersect(ray,C,normal,d+np.asarray(bounds))
        result={}
        for frame in (*FIT_VIEWS,RESERVED):
            Rt,Ct=poses[by[frame]['source_name']];xx,yy,_=erp.project(world,Rt,Ct,W,H);dx=(xx[1]-xx[0]+W/2)%W-W/2;dy=yy[1]-yy[0];valid=positive.all(axis=0);values=np.hypot(dx[valid],dy[valid])
            result[str(frame)]={'count':int(len(values)),'p50_p90_max_native_px':np.percentile(values,[50,90,100]).tolist() if len(values) else None}
        return result
    inlier_disp=range_displacements([lo,hi]);all_disp=range_displacements([all_lo,all_hi])
    plan={'reference':REFERENCE,'fit_views':FIT_VIEWS,'reserved':RESERVED,'roi_xywh':ROI,'plane_normal':normal.tolist(),'plane_d':d,'median_range_model_units':median,'plane_tolerance':median*.005,'inlier_offsets_model_units':[lo,hi],'all_supported_offsets_model_units':[all_lo,all_hi],'inlier_range_displacements':inlier_disp,'all_supported_range_displacements':all_disp,'offset_samples':len(offsets),'landmarks':len(P),'inliers':int(inliers.sum()),'max_distance_to_inlier_native_px':20,'stride_native_px':4 if a.fixed_plane_prior else 8,'patch_size':7,'minimum_ncc_all_fit_views':.8,'minimum_unique_ncc_margin_each_view':None if a.fixed_plane_prior else .03,'minimum_competing_projection_distance_native_px':1.0,'minimum_reserved_ncc':.8,'reserved_uniqueness_margin':None if a.fixed_plane_prior else .03,'competitor_margin_report_threshold':.03,'minimum_source_std_8bit':5,'plane_source':'in-sample original SfM; competitors span all supported-point residual extrema, while the inlier span is reported separately; not independent geometry'}
    if a.describe:print(json.dumps(plan,indent=2));return
    targets=[];records={}
    for i in ids:
        row=by[i];ip=a.prepared/'images'/row['name'];mp=a.prepared/'masks'/row['name'];im=cv2.imread(str(ip),0);m=cv2.imread(str(mp),0)
        if im is None or m is None or im.shape!=(H,W) or m.shape!=(H,W):raise ValueError('Invalid view')
        records[str(i)]={'name':row['name'],'pts_microseconds':row['timestamp_microseconds'],'image_sha256':sha(ip),'mask_sha256':sha(mp)}
        if i!=REFERENCE:targets.append((im,m,poses[row['source_name']]))
    counts=Counter();accepted=[];source_color=cv2.imread(str(a.prepared/'images'/ref['name']),cv2.IMREAD_COLOR);overlay=source_color.copy();plane_scores=[]
    stride=4 if a.fixed_plane_prior else 8
    for py in range(y+3,y+h-3,stride):
      for px in range(x+3,x+w-3,stride):
        if time.monotonic()-start>a.timeout:raise TimeoutError('Deadline exceeded')
        if cv2.pointPolygonTest(hull,(float(px),float(py)),False)<0 or np.min(np.linalg.norm(measured-[px,py],axis=1))>20:continue
        scores,reason=patch_scores(image,mask,(R,C),targets[:3],px,py,offsets,normal)
        if reason is None:
            scores,coordinates=scores
            k,uniqueness=select(scores,coordinates)
            measured_index=int(np.argmin(np.abs(offsets-d)))
            fixed_scores=scores[:,measured_index]
            plane_scores.append({'xy':[px,py],'fit_ncc_at_measured_plane':fixed_scores.tolist() if np.all(np.isfinite(fixed_scores)) else None})
            if a.fixed_plane_prior:
                reason=None if np.all(np.isfinite(fixed_scores)) and np.min(fixed_scores)>=.8 else 'fixed_plane_low_or_masked'
                k=measured_index
            else:reason=uniqueness
        if reason is None:
            reserved,rr=patch_scores(image,mask,(R,C),targets[3:],px,py,offsets,normal)
            if rr:reason='reserved_'+rr
            else:
                reserved,reserved_coordinates=reserved
                if not np.isfinite(reserved[0,k]) or reserved[0,k]<.8:reason='reserved_low_or_masked'
                elif not a.fixed_plane_prior:
                    alternatives=reserved[0][separated_competitors(reserved_coordinates[0],k) & np.isfinite(reserved[0])]
                    if not len(alternatives):reason='reserved_depth_unresolved'
                    elif reserved[0,k]-alternatives.max()<.03:reason='reserved_ambiguous'
        if reason:counts[reason]+=1;cv2.circle(overlay,(px,py),1,(0,0,255),-1)
        else:
            ray=erp.rays(px,py,W,H)@R;world,positive=intersect(ray[None,:],C,normal,[offsets[k]])
            margins=competitor_margins(scores,coordinates,k)+competitor_margins(reserved,reserved_coordinates,k)
            depth_status=('unresolved' if any(v is None for v in margins) else 'separated_at_fixed_plane' if min(margins)>=.03 else 'ambiguous_at_fixed_plane')
            accepted.append({'xy':[px,py],'xyz':world[0,0].tolist(),'offset':float(offsets[k]-d),'fit_ncc':scores[:,k].tolist(),'reserved_ncc':float(reserved[0,k]),'depth_competitor_result':depth_status,'depth_competitor_ncc_margins':margins,'rgb':source_color[py,px,::-1].tolist()})
            cv2.circle(overlay,(px,py),2,(0,255,0),-1)
    a.output.mkdir(parents=True);cv2.polylines(overlay,[hull.astype(np.int32)],True,(255,255,0),1);cv2.imwrite(str(a.output/'support.png'),overlay)
    report={'mode':'fixed_measured_plane_prior' if a.fixed_plane_prior else 'depth_unique_sweep','method':('Provisional initialization interpolated on measured plane; not independently triangulated depth. ' if a.fixed_plane_prior else '')+'Source-ray patch sweep inside measured-landmark convex hull and within 20 native pixels of an inlier. Only original training images, mask footprints and original SfM gauge; reserved view never selects the depth. Repeated data/poses were used by SfM; outputs are provisional, not independent depth truth. No virtual views, no image adjustment, no model insertion.','plan':plan,'input_views':records,'model_sha256':{n:sha(a.model/n) for n in ('cameras.bin','images.bin','points3D.bin')},'manifest_sha256':sha(a.prepared/'manifest.json'),'script_sha256':sha(Path(__file__)),'sampled':sum(counts.values())+len(accepted),'rejections':dict(counts),'accepted':accepted,'measured_plane_scores':plane_scores,'plane_landmarks':[{'xy':[u,v],'point_id':int(pid),'inlier':bool(ok),'signed_residual':float(rr)} for (u,v,pid),ok,rr in zip(selected,inliers,res)],'overlay_sha256':sha(a.output/'support.png'),'elapsed_seconds':time.monotonic()-start}
    if a.fixed_plane_prior and accepted:
        xyz=np.array([r['xyz'] for r in accepted]);rgb=np.array([r['rgb'] for r in accepted],dtype=np.uint8)
        if len(xyz)>6505 or len(np.unique(xyz,axis=0))!=len(xyz) or len(np.unique(rgb,axis=0))<2:raise ValueError('Invalid duplicate or constant-color prior')
        if len(xyz)<5:raise ValueError('At least five points required to evaluate four-neighbor scale')
        distance,_=cKDTree(xyz).query(xyz,k=5);rms=np.sqrt(np.mean(distance[:,1:]**2,axis=1));scales=.35*rms
        if np.any(~np.isfinite(scales)) or np.any(scales<=0):raise ValueError('Invalid neighbor scales')
        seed=a.output/'plane-prior.ply'
        with seed.open('w') as f:
            f.write('ply\nformat ascii 1.0\n' + f'element vertex {len(xyz)}\n' + 'property float x\nproperty float y\nproperty float z\nproperty uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n')
            for point,color in zip(xyz,rgb):f.write(' '.join(map(str,[*point,*color]))+'\n')
        report['seed']={'path':str(seed),'sha256':sha(seed),'points':len(xyz),'unique_colors':len(np.unique(rgb,axis=0)),'four_neighbor_rms_model_units_p10_p50_p90':np.percentile(rms,[10,50,90]).tolist(),'initializer_scale_0_35_rms_model_units_p10_p50_p90':np.percentile(scales,[10,50,90]).tolist(),'note':'Initializer scale estimate, not an asserted measured surface thickness; PLY stores only XYZ/RGB.'}
    (a.output/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    if sum(p.stat().st_size for p in a.output.iterdir() if p.is_file())>5_000_000:raise ValueError('Output budget exceeded')
    print(json.dumps({'plan':plan,'sampled':report['sampled'],'rejections':dict(counts),'accepted':len(accepted),'elapsed_seconds':report['elapsed_seconds']},indent=2))
if __name__=='__main__':main()
