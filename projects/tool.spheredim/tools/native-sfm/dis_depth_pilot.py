#!/usr/bin/env python3
"""Full-ERP temporal DIS correspondence diagnostic; never emits seed geometry."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import time
import cv2
import numpy as np
import compare_rigs as rig
from audit_seed_gauge import read_erp_cameras
import temporal_depth_roi as depth

W,H=2048,1024

def flow_initial(R0,R1,pad):
    y,x=np.indices((H,W+2*pad),dtype=np.float32);x0=np.mod(x-pad,W)
    ray=depth.rays(x0,y,W,H); target=ray@R0@R1.T
    tx=(np.arctan2(target[...,0],target[...,2])/(2*np.pi)+.5)*W
    ty=(np.arctan2(target[...,1],np.hypot(target[...,0],target[...,2]))/np.pi+.5)*H
    dx=(tx-x0+W/2)%W-W/2
    return np.stack((dx,ty-y),axis=-1).astype(np.float32)


def dis_flow(image0, image1, R0, R1, pad=256):
    """Estimate full-ERP flow with a wrapped halo and rotation-only initialization."""
    a = cv2.copyMakeBorder(image0, 0, 0, pad, pad, cv2.BORDER_WRAP)
    b = cv2.copyMakeBorder(image1, 0, 0, pad, pad, cv2.BORDER_WRAP)
    initial = flow_initial(R0, R1, pad)
    dis = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_FAST)
    dis.setFinestScale(0)
    return dis.calc(a, b, initial)[:, pad:pad + W].copy()


def wrapped_delta(a,b,width=W):
    return (a-b+width/2)%width-width/2


def sample_flow(flow, x, y):
    """Bilinear flow sample with periodic longitude and bounded latitude."""
    h, w = flow.shape[:2]
    x = x % w
    x0, y0 = int(np.floor(x)), int(np.floor(y))
    if y0 < 0 or y0 + 1 >= h:
        raise ValueError('Flow sample outside latitude support')
    fx, fy = x - x0, y - y0
    a = flow[y0, x0] * (1 - fx) + flow[y0, (x0 + 1) % w] * fx
    b = flow[y0 + 1, x0] * (1 - fx) + flow[y0 + 1, (x0 + 1) % w] * fx
    return a * (1 - fy) + b * fy


def triangulate(x0,y0,x1,y1,pose0,pose1):
    R0,C0=pose0;R1,C1=pose1
    d0=R0.T@depth.rays(x0,y0,W,H);d1=R1.T@depth.rays(x1,y1,W,H)
    point,reason=rig.triangulate((C0,d0),(C1,d1),min_angle=2)
    return point,reason


def full_mask(mask,x,y,radius):
    x=np.asarray(x);y=np.asarray(y);ix=np.floor(x).astype(int);iy=np.floor(y).astype(int)
    if np.any(iy-radius<0) or np.any(iy+radius+1>=H):return False
    return all(np.all(mask[(iy+dy),np.mod(ix+dx,W)]==255) for dx in range(-radius,radius+2) for dy in range(-radius,radius+2))


def patch(image,mask,x,y):
    dx,dy=np.meshgrid(np.arange(-3,4),np.arange(-3,4));return depth.sample(image,mask,x+dx,y+dy)


def unique_depth(reference,target,mask0,mask1,x,y,point,pose0,pose1):
    R0,C0=pose0;R1,C1=pose1;src,valid=patch(reference,mask0,x,y)
    if not valid.all():return False,'mask'
    distance=np.linalg.norm(point-C0);scores=[]
    dx,dy=np.meshgrid(np.arange(-3,4),np.arange(-3,4))
    patch_rays=depth.rays(x+dx,y+dy,W,H)@R0
    for factor in (.5,.7,.85,1.,1.15,1.3,1.5):
        world=C0+patch_rays*(distance*factor)
        xx,yy,_=depth.project(world,R1,C1,W,H)
        dst,valid=depth.sample(target,mask1,xx,yy)
        if not valid.all() or np.std(dst)<1e-5:scores.append(None);continue
        a=src-src.mean();b=dst-dst.mean();scores.append(float(np.sum(a*b)/max(np.sqrt(np.sum(a*a)*np.sum(b*b)),1e-12)))
    if scores[3] is None or sum(v is not None for i,v in enumerate(scores) if i!=3)<2:return False,'uniqueness_unmeasured'
    if scores[3]<.8 or scores[3]-max(v for i,v in enumerate(scores) if i!=3 and v is not None)<.05:return False,'ambiguous_texture'
    return True,None


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('prepared',type=Path);p.add_argument('model',type=Path);p.add_argument('output',type=Path);p.add_argument('--timeout',type=int,default=170);a=p.parse_args();start=time.monotonic()
    if a.output.exists():raise FileExistsError(a.output)
    manifest=json.loads((a.prepared/'manifest.json').read_text());frames={}
    for row in manifest['frames']:
        if row['lens']!='cam0':continue
        if row['source_frame'] in frames:raise ValueError('Duplicate cam0 source frame')
        frames[row['source_frame']]=row
    ids=[1435,1430,1445,1450]
    if any(frames[i]['split']!='train' or frames[i]['name'] in manifest['heldout_evaluation_order'] for i in ids):raise ValueError('All input captures must be training frames')
    cameras=read_erp_cameras(a.model/'cameras.bin')
    if any(v[:2]!=(W,H) or not np.allclose(v[2:],[W,H],rtol=0,atol=1e-9) for v in cameras.values()):raise ValueError('Expected full-sphere native ERP cameras')
    poses=rig.read_binary_poses(a.model/'images.bin');items=[];inputs={}
    def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
    for frame in ids:
        row=frames[frame];ip=a.prepared/'images'/row['name'];mp=a.prepared/'masks'/row['name'];im=cv2.imread(str(ip),0);mask=cv2.imread(str(mp),0)
        if im is None or mask is None or im.shape!=(H,W) or mask.shape!=(H,W):raise ValueError('Expected native ERP images and masks')
        items.append((im,mask,poses[row['source_name']]));inputs[str(frame)]={'name':row['name'],'source_name':row['source_name'],'pts_microseconds':row['timestamp_microseconds'],'image_sha256':sha(ip),'mask_sha256':sha(mp)}
    cv2.setNumThreads(2);pad=256;flows=[];ref,mask0,pose0=items[0]
    for target,mask1,pose1 in items[1:]:
        if time.monotonic()-start>a.timeout:raise TimeoutError('Pilot exceeded time limit')
        f=dis_flow(ref,target,pose0[0],pose1[0],pad)
        b=dis_flow(target,ref,pose1[0],pose0[0],pad)
        flows.append((f,b))
    positions=[(x,y) for y in range(663,727,8) for x in range(803,1077,8)];std=[]
    for x,y in positions:
        src,ok=patch(ref,mask0,x,y)
        if ok.all():std.append(float(np.std(src)))
    if not std:raise ValueError('No valid source patches')
    texture_threshold=max(2.,.5*float(np.median(std)));reasons=Counter();accepted=[];view_failures={str(t):Counter() for t in ids[1:]};fb_values={str(t):[] for t in ids[1:]};overlay=cv2.cvtColor(ref,cv2.COLOR_GRAY2BGR)
    for x,y in positions:
        if time.monotonic()-start>a.timeout:raise TimeoutError('Pilot exceeded time limit')
        src,ok=patch(ref,mask0,x,y);reason=None;observed=[];points=[]
        if not full_mask(mask0,x,y,16) or not ok.all():reason='reference_mask'
        elif float(np.std(src))<texture_threshold:reason='reference_low_texture'
        else:
            for frame,(target,mask1,pose1),(forward,backward) in zip(ids[1:],items[1:],flows):
                u,v=forward[y,x];tx=(x+float(u))%W;ty=y+float(v)
                if not np.isfinite([tx,ty]).all() or not full_mask(mask1,tx,ty,16):reason='target_mask';view_failures[str(frame)][reason]+=1;break
                t=sample_flow(backward,tx,ty);err=np.hypot(wrapped_delta(tx+float(t[0]),x),ty+float(t[1])-y)
                fb_values[str(frame)].append(float(err))
                if err>1:reason='forward_backward';view_failures[str(frame)][reason]+=1;break
                point,why=triangulate(x,y,tx,ty,pose0,pose1)
                if why:reason='triangulation_'+why;view_failures[str(frame)][reason]+=1;break
                good,why=unique_depth(ref,target,mask0,mask1,x,y,point,pose0,pose1)
                if not good:reason=why;view_failures[str(frame)][reason]+=1;break
                observed.append((tx,ty));points.append(point)
        if reason is None:
            # Pairwise triangulations must predict every other measured view.
            for point in points:
                for (_,_,pose1),(tx,ty) in zip(items[1:],observed):
                    xx,yy,_=depth.project(point,*pose1,W,H)
                    if np.hypot(wrapped_delta(xx,tx),yy-ty)>2:reason='multiview_reprojection';break
                if reason:break
        if reason:reasons[reason]+=1;cv2.circle(overlay,(x,y),1,(0,0,255),-1)
        else:accepted.append({'xy':[x,y],'neighbors_xy':observed});cv2.circle(overlay,(x,y),2,(0,255,0),-1)
    a.output.mkdir(parents=True);cv2.rectangle(overlay,(800,660),(1079,729),(255,255,0),1);cv2.imwrite(str(a.output/'overlay.png'),overlay)
    report={'method':'DIS FAST full native ERP with 256-pixel longitude wrap padding and rotation initialization. No virtual views, altered source or seed output. Forward/backward uses bilinear subpixel flow sampling with periodic longitude. Source and target mask footprints are checked; DIS pyramids can still be influenced by masked content beyond this 16-pixel guard, so acceptance is provisional. Constant-radial depth patch uniqueness is a diagnostic approximation. Native SfM poses use all frames including splat holdouts, but only training pixels are used here.','inputs':inputs,'model_images_sha256':sha(a.model/'images.bin'),'model_cameras_sha256':sha(a.model/'cameras.bin'),'manifest_sha256':sha(a.prepared/'manifest.json'),'script_sha256':sha(Path(__file__)),'config':{'roi_xywh':[800,660,280,70],'stride':8,'padding':pad,'dis_preset':'FAST','dis_finest_scale':0,'dis_patch_size':8,'dis_patch_stride':4,'fb_max_native_px':1,'cross_view_max_native_px':2,'min_parallax_degrees':2,'source_patch_std_8bit_min':texture_threshold,'source_patch_std_median_8bit':float(np.median(std)),'uniqueness_ncc_min':.8,'uniqueness_margin':.05,'depth_factors':[.5,.7,.85,1,1.15,1.3,1.5]},'sampled':len(positions),'rejections':dict(reasons),'per_neighbor_note':'Sequential first-failure counts; later neighbors are evaluated only when earlier checks pass.', 'per_neighbor_failures':{k:dict(v) for k,v in view_failures.items()},'per_neighbor_fb_native_px_p50_p90':{k:(np.percentile(v,[50,90]).tolist() if v else None) for k,v in fb_values.items()},'accepted':accepted,'elapsed_seconds':time.monotonic()-start,'overlay_sha256':sha(a.output/'overlay.png')}
    (a.output/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n');print(json.dumps({k:report[k] for k in ('sampled','rejections','elapsed_seconds')},indent=2));print('accepted',len(accepted))
if __name__=='__main__':main()
