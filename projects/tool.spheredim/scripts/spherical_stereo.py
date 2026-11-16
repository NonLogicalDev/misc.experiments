#!/usr/bin/env python3
"""Rectified native-ERP stereo diagnostic; unmatched output remains invalid."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import cv2
import numpy as np
import torch
import torch.nn.functional as F


def basis_for_baseline(b):
    b=np.asarray(b,dtype=np.float64);b=b/np.linalg.norm(b)
    ref=np.array([0.,0.,1.]) if abs(b[2])<.9 else np.array([0.,1.,0.])
    a=np.cross(ref,b);a/=np.linalg.norm(a);c=np.cross(b,a)
    return np.column_stack((a,c,b))


def rectified_rays(width,height,basis):
    lon=(np.arange(width)+.5)*2*np.pi/width;lat=np.pi/2-(np.arange(height)+.5)*np.pi/height
    cl=np.cos(lat)[:,None];r=np.stack(np.broadcast_arrays(cl*np.cos(lon)[None,:],-cl*np.sin(lon)[None,:],np.sin(lat)[:,None]),axis=-1)
    return r@basis.T


def source_coordinates(rays,width,height):
    lon=np.mod(np.arctan2(-rays[...,1],rays[...,0]),2*np.pi);lat=np.arcsin(np.clip(rays[...,2],-1,1))
    return (lon*width/(2*np.pi)-.5).astype(np.float32),((np.pi/2-lat)*height/np.pi-.5).astype(np.float32)


def remap(image,mask,rays):
    h,w=mask.shape;x,y=source_coordinates(rays,w,h);valid_y=(y>=0)&(y<=h-1)
    # One wrapped horizontal border lets bilinear samples straddle longitude zero.
    rgb=cv2.remap(cv2.copyMakeBorder(image,0,0,1,1,cv2.BORDER_WRAP),x+1,y,cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT)
    keep=cv2.remap(cv2.copyMakeBorder((mask>127).astype(np.float32),0,0,1,1,cv2.BORDER_WRAP),x+1,y,cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT)
    return rgb,(keep>=1-1e-6)&valid_y,x,y


def stereo_ncc(image0,image1,mask0,mask1,max_shift,patch,device='cpu',minimum=.8,uniqueness=.03,variance=1e-4):
    if patch%2!=1 or patch<3 or max_shift<1:raise ValueError('Invalid stereo search')
    dev=torch.device(device)
    def tensor(x):return torch.as_tensor(x,dtype=torch.float32,device=dev)[None,None]
    a,b=tensor(image0),tensor(image1);ma,mb=tensor(mask0),tensor(mask1)
    def search(left,right,lmask,rmask,direction):
        scores=[];eligible=torch.zeros_like(left,dtype=torch.bool);pad=patch//2
        for d in range(1,max_shift+1):
            shifted=torch.zeros_like(right);sm=torch.zeros_like(rmask)
            if direction==1:shifted[:,:,:-d,:]=right[:,:,d:,:];sm[:,:,:-d,:]=rmask[:,:,d:,:]
            else:shifted[:,:,d:,:]=right[:,:,:-d,:];sm[:,:,d:,:]=rmask[:,:,:-d,:]
            valid=lmask*sm
            def avg(v):return F.avg_pool2d(v,patch,stride=1,padding=pad,count_include_pad=True)
            full=avg(valid)>=1-1e-6;ax=avg(left);bx=avg(shifted)
            va=(avg(left*left)-ax*ax).clamp_min(0);vb=(avg(shifted*shifted)-bx*bx).clamp_min(0)
            supported=full & (va>variance) & (vb>variance);eligible |= supported
            corr=(avg(left*shifted)-ax*bx)/torch.sqrt((va*vb).clamp_min(1e-12))
            scores.append(torch.where(supported,corr,torch.full_like(corr,-2)))
        volume=torch.stack(scores,dim=0);best,index=volume.max(dim=0)
        offsets=torch.arange(max_shift,device=dev)[:,None,None,None,None]
        competitor=torch.where(torch.abs(offsets-index.unsqueeze(0))>2,volume,torch.full_like(volume,-2)).max(dim=0).values
        prev=volume.gather(0,(index-1).clamp(min=0).unsqueeze(0)).squeeze(0)
        nxt=volume.gather(0,(index+1).clamp(max=max_shift-1).unsqueeze(0)).squeeze(0)
        denom=prev-2*best+nxt
        sub=torch.where((index>0)&(index<max_shift-1)&(prev>-1)&(nxt>-1)&(denom< -1e-6),.5*(prev-nxt)/torch.minimum(denom,torch.full_like(denom,-1e-6)),torch.zeros_like(best)).clamp(-.5,.5)
        shift=index.float()+1+sub;margin=best-competitor
        return shift,best,(best>=minimum)&(margin>=uniqueness),margin,eligible
    with torch.no_grad():
        f,score,valid,margin,eligible=search(a,b,ma,mb,1);forward_good=valid.clone();back,_,back_valid,_,_=search(b,a,mb,ma,-1)
        h,w=image0.shape;yy=torch.arange(h,device=dev)[None,None,:,None].expand_as(f);xx=torch.arange(w,device=dev)[None,None,None,:].expand_as(f)
        y=yy+f; y0=torch.floor(y).long().clamp(0,h-1);y1=(y0+1).clamp(max=h-1);t=(y-y0.float()).clamp(0,1)
        def get(arr,row):return arr.reshape(-1)[(row*w+xx).reshape(-1)].reshape_as(f)
        reverse=get(back,y0)*(1-t)+get(back,y1)*t
        rev_valid=(get(back_valid.float(),y0)>0)&((t<1e-6)|(get(back_valid.float(),y1)>0))
        valid=valid&rev_valid&(torch.abs(f-reverse)<=1)&(y<h-1)
        return f[0,0].cpu().numpy(),score[0,0].cpu().numpy(),valid[0,0].cpu().numpy(),margin[0,0].cpu().numpy(),eligible[0,0].cpu().numpy(),forward_good[0,0].cpu().numpy(),torch.abs(f-reverse)[0,0].cpu().numpy()


def triangulate(r0,r1,baseline):
    dot=np.sum(r0*r1,axis=-1);den=1-dot*dot;tb=np.sum(r0*baseline,axis=-1);ta=np.sum(r1*baseline,axis=-1)
    d0=(tb-dot*ta)/np.maximum(den,1e-12);d1=(dot*tb-ta)/np.maximum(den,1e-12)
    p0=r0*d0[...,None];p1=baseline+r1*d1[...,None];gap=np.linalg.norm(p0-p1,axis=-1)
    return (p0+p1)/2,(den>1e-8)&(d0>0)&(d1>0),gap


def validate_features(image0,image1,mask0,mask1,valid,x0,y0,x1,y1,score,margin,reverse_error,rotation,baseline):
    # Feature correspondences are independent of the dense matcher, not ground truth.
    from scipy.spatial import cKDTree
    from fit_static_lens_alignment import matches,rays
    from fit_lens_rig import epipolar
    p0,p1=matches(image0,image1,mask0,mask1)
    yy,xx=np.where(valid);records=[]
    if not len(yy): return {'sift_matches':len(p0),'records':records,'distinct_rig_consistent':0}
    distance,nearest=cKDTree(np.column_stack((x0[valid],y0[valid]))).query(p0)
    for i in np.flatnonzero(distance<2):
        y,x=yy[nearest[i]],xx[nearest[i]];dx=abs(float(x1[y,x])-p1[i,0]);dx=min(dx,image0.shape[1]-dx)
        error=float(np.hypot(dx,float(y1[y,x])-p1[i,1]))
        residual=float(np.rad2deg(abs(epipolar(rays([p1[i]],image0.shape[1],image0.shape[0]),rays([p0[i]],image0.shape[1],image0.shape[0]),rotation,baseline)[0])))
        records.append({'source0_xy':p0[i].tolist(),'sift_lens1_xy':p1[i].tolist(),'stereo_lens1_xy':[float(x1[y,x]),float(y1[y,x])],
                        'source_distance_px':float(distance[i]),'lens1_error_px':error,'sift_epipolar_residual_deg':residual,
                        'ncc':float(score[y,x]),'peak_margin':float(margin[y,x]),'reverse_error_px':float(reverse_error[y,x])})
    unique=[]
    for row in records:
        if row['sift_epipolar_residual_deg']>=.2 or any(np.linalg.norm(np.array(row['source0_xy'])-np.array(prev['source0_xy']))<1 for prev in unique):continue
        unique.append(row)
    errors=np.array([row['lens1_error_px'] for row in unique])
    return {'sift_matches':len(p0),'within_2px_accepted':len(records),'rig_filter_degrees':.2,'deduplicate_source_within_px':1,
            'distinct_rig_consistent':len(unique),'median_error_px':float(np.median(errors)) if len(errors) else None,
            'p90_error_px':float(np.percentile(errors,90)) if len(errors) else None,'max_error_px':float(errors.max()) if len(errors) else None,'records':records}


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for v in iter(lambda:f.read(1024*1024),b''):h.update(v)
    return h.hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('manifest',type=Path);p.add_argument('rig',type=Path);p.add_argument('output',type=Path);p.add_argument('--frame',type=int,default=989);p.add_argument('--x-start',type=int,default=768);p.add_argument('--x-end',type=int,default=1280);p.add_argument('--max-shift',type=int,default=48);p.add_argument('--patch',type=int,default=9);p.add_argument('--device',choices=('mps','cpu'),default='mps');p.add_argument('--validate-features',action='store_true');a=p.parse_args()
    if a.output.exists():p.error('Output must be new')
    if shutil.disk_usage(a.output.parent).free<36*1024**3:p.error('Need 35 GiB reserve plus 1 GiB output budget')
    if a.device=='mps' and not torch.backends.mps.is_available():p.error('MPS is unavailable')
    doc=json.loads(a.manifest.read_text());rows=[r for r in doc['frames'] if r['frame']==a.frame]
    if len(rows)!=1:raise ValueError('Frame must be unique')
    row=rows[0];paths={k:Path(row[k]) for k in ('lens0','lens1','mask0','mask1')}
    if any(sha(path)!=row[k+'_sha256'] for k,path in paths.items()):raise ValueError('Input hash mismatch')
    im0=cv2.imread(str(paths['lens0']));im1=cv2.imread(str(paths['lens1']));m0=cv2.imread(str(paths['mask0']),0);m1=cv2.imread(str(paths['mask1']),0)
    h,w=m0.shape
    if w!=2*h or im0.shape!=im1.shape or im0.shape[:2]!=(h,w) or m1.shape!=(h,w) or not 0<=a.x_start<a.x_end<=w:raise ValueError('Input dimensions or band invalid')
    rig=json.loads(a.rig.read_text());R=np.array(rig['rotation_matrix']);baseline=np.array(rig['baseline_direction']);baseline=baseline/np.linalg.norm(baseline);basis=basis_for_baseline(baseline)
    rays=rectified_rays(w,h,basis)[:,a.x_start:a.x_end];rgb0,v0,x0,y0=remap(im0,m0,rays);rgb1,v1,x1,y1=remap(im1,m1,rays@R)
    g0=cv2.cvtColor(rgb0,cv2.COLOR_BGR2GRAY).astype(np.float32)/255;g1=cv2.cvtColor(rgb1,cv2.COLOR_BGR2GRAY).astype(np.float32)/255
    shift,score,valid,margin,eligible,forward_good,reverse_error=stereo_ncc(g0,g1,v0,v1,a.max_shift,a.patch,a.device);yy,xx=np.indices(valid.shape);yf=np.clip(yy+shift,0,h-1);ylo=np.floor(yf).astype(int);yhi=np.minimum(ylo+1,h-1);fraction=yf-ylo
    ray1=rays[ylo,xx]*(1-fraction[...,None])+rays[yhi,xx]*fraction[...,None];ray1/=np.maximum(np.linalg.norm(ray1,axis=-1,keepdims=True),1e-12)
    points,positive,gap=triangulate(rays,ray1,baseline);valid &=positive&(gap<.05)
    x1sub,y1sub=source_coordinates(ray1@R,w,h)
    # Sparse z-buffered samples in central ERP; no interpolation or hole filling.
    center=baseline*.5;relative=points-center;distance=np.linalg.norm(relative,axis=-1);directions=relative/np.maximum(distance[...,None],1e-12);cx,cy=source_coordinates(directions,w,h);ix=np.rint(cx).astype(int)%w;iy=np.rint(cy).astype(int);valid&=(iy>=0)&(iy<h)&np.isfinite(distance)
    indices=np.flatnonzero(valid);order=indices[np.argsort(distance.ravel()[indices])[::-1]];canvas=np.zeros((h,w,3),np.uint8);keep=np.zeros((h,w),np.uint8);src=np.full((h,w,4),-1,np.float32);depth=np.zeros((h,w),np.float32)
    for j in order:
        r,c=np.unravel_index(j,valid.shape);u,v=ix[r,c],iy[r,c];canvas[v,u]=rgb0[r,c];keep[v,u]=255;depth[v,u]=distance[r,c];src[v,u]=[x0[r,c],y0[r,c],x1sub[r,c],y1sub[r,c]]
    # Compare identical rectified pixels where both rotation-only and stereo samples exist.
    aligned=cv2.remap(rgb1,xx.astype(np.float32),yf.astype(np.float32),cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT)
    comparison=valid & v1
    reference=np.where(comparison[...,None],rgb0,0).astype(np.uint8)
    static=np.where(comparison[...,None],rgb1,0).astype(np.uint8)
    stereo=np.where(comparison[...,None],aligned,0).astype(np.uint8)
    diff_static=np.abs(rgb0.astype(np.float32)-rgb1.astype(np.float32)).mean(axis=-1)
    diff_stereo=np.abs(rgb0.astype(np.float32)-aligned.astype(np.float32)).mean(axis=-1)
    feature=validate_features(im0,im1,m0,m1,valid,x0,y0,x1sub,y1sub,score,margin,reverse_error,R,baseline) if a.validate_features else None
    a.output.mkdir();cv2.imwrite(str(a.output/'central-samples.png'),canvas);cv2.imwrite(str(a.output/'validity.png'),keep)
    for name,image in [('overlap-reference.png',reference),('overlap-rotation-only.png',static),('overlap-stereo-aligned.png',stereo),('overlap-comparison-mask.png',comparison.astype(np.uint8)*255)]:cv2.imwrite(str(a.output/name),image)
    if feature is not None:(a.output/'feature-validation.json').write_text(json.dumps(feature,indent=2)+'\n')
    np.savez_compressed(a.output/'provenance.npz',source_xy=src,depth_baselines=depth,origin=center,baseline_direction=baseline,rectified_disparity=shift,rectified_score=score,rectified_margin=margin,rectified_eligible=eligible,rectified_forward_good=forward_good,rectified_reverse_error=reverse_error,rectified_valid=valid)
    report={'frame':a.frame,'device':a.device,'image_size':[w,h],'rectified_x_band':[a.x_start,a.x_end],'patch':a.patch,'max_disparity_pixels':a.max_shift,'minimum_ncc':.8,'distinct_peak_margin':.03,'peak_exclusion_radius':2,'eligible_patch_pixels':int(eligible.sum()),'accepted_fraction_of_eligible':float(valid.sum()/eligible.sum()) if eligible.any() else None,'forward_confident_count':int(forward_good.sum()),'forward_rejected_by_reverse_or_geometry':int((forward_good & ~valid).sum()),'comparison_pixels':int(comparison.sum()),'rotation_only_rgb_mae_255':float(diff_static[comparison].mean()) if comparison.any() else None,'stereo_rgb_mae_255':float(diff_stereo[comparison].mean()) if comparison.any() else None,'valid_stereo_matches':int(valid.sum()),'central_output_pixels':int((keep>0).sum()),'median_disparity_pixels':float(np.median(shift[valid])) if valid.any() else None,'median_gap_baseline_units':float(np.median(gap[valid])) if valid.any() else None,'origin':'baseline midpoint, baseline length one; no metric calibration claimed','validity_meaning':'passed heuristic correspondence and geometry filters; not independently verified surface truth','gap_interpretation':'same-meridian constraint makes ray gap near zero by construction, not evidence of correct correspondence','independent_feature_validation':{k:v for k,v in feature.items() if k!='records'} if feature is not None else None,'method':'full ERP baseline-pole rectification, masked patch NCC, reverse consistency, positive ray depths, nearest-pixel z-buffer; unfilled invalid holes','input_sha256':{k:sha(v) for k,v in paths.items()},'rig_sha256':sha(a.rig)}
    (a.output/'manifest.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
