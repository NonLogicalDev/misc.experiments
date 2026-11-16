#!/usr/bin/env python3
"""Inspect native ERP depth support in masked training captures; unmatched pixels stay unknown."""
import argparse
import hashlib
import json
import time
from pathlib import Path

import cv2
import numpy as np
import compare_density_models as modelio
import compare_rigs as rig


def rays(x, y, width, height):
    lon = (np.asarray(x) / width - .5) * (2 * np.pi)
    lat = (np.asarray(y) / height - .5) * np.pi
    return np.stack(np.broadcast_arrays(np.sin(lon) * np.cos(lat), np.sin(lat), np.cos(lon) * np.cos(lat)), axis=-1)


def project(points, rotation, center, width, height):
    p = (points - center) @ rotation.T
    length = np.linalg.norm(p, axis=-1)
    x = (np.arctan2(p[..., 0], p[..., 2]) / (2 * np.pi) + .5) * width
    y = (np.arctan2(p[..., 1], np.hypot(p[..., 0], p[..., 2])) / np.pi + .5) * height
    return x, y, length


def sample(image, mask, x, y):
    """Require every bilinear source pixel to be valid, including across the ERP seam."""
    h, w = mask.shape
    x = np.asarray(x, np.float32); y = np.asarray(y, np.float32)
    xi = np.floor(x).astype(int) % w; yi = np.floor(y).astype(int)
    inside = (yi >= 0) & (yi + 1 < h)
    y0 = np.clip(yi, 0, h - 1); y1 = np.clip(yi + 1, 0, h - 1); x1 = (xi + 1) % w
    valid = inside & (mask[y0, xi] == 255) & (mask[y0, x1] == 255) & (mask[y1, xi] == 255) & (mask[y1, x1] == 255)
    padded = cv2.copyMakeBorder(image, 0, 0, 1, 1, cv2.BORDER_WRAP)
    vals = cv2.remap(padded, (np.mod(x, w) + 1).reshape(1, -1), y.reshape(1, -1), cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT).reshape(x.shape)
    return vals, valid


def select_depth(scores, depths, minimum=.8, margin=.05, min_views=2):
    """Reject boundary peaks, repeated peaks and any unstable leave-one-view consensus."""
    scores = np.asarray(scores, float)
    support = scores >= minimum
    count = support.sum(axis=0)
    available = scores > -2
    available_count = available.sum(axis=0)
    avg = np.divide(np.where(support, scores, 0).sum(axis=0), count, out=np.full(len(depths), -2.), where=count >= min_views)
    k = int(np.argmax(avg))
    if k == 0 or k == len(depths)-1 or count[k] < min_views:
        return None, 'insufficient_support_or_boundary'
    competition = np.divide(np.where(available,scores,0).sum(axis=0), available_count, out=np.full(len(depths),-2.), where=available_count>=min_views);competition[max(0,k-2):min(len(depths),k+3)] = -2
    if np.max(competition) <= -2 or avg[k] - np.max(competition) < margin:
        return None, 'ambiguous_peak'
    # Each contributing view must independently prefer this basin over competing depths.
    used = np.flatnonzero(support[:, k])
    for v in used:
        other = scores[v].copy();other[max(0,k-2):min(len(depths),k+3)] = -2
        if np.max(other) <= -2 or scores[v,k] - np.max(other) < margin:
            return None, 'view_ambiguous'
    if len(used) >= 3:
        for v in used:
            keep = np.delete(scores, v, axis=0); good = keep >= minimum; c = good.sum(axis=0)
            a = np.divide(np.where(good,keep,0).sum(axis=0),c,out=np.full(len(depths),-2.),where=c>=min_views)
            if abs(int(np.argmax(a))-k)>2:
                return None, 'leave_one_out_unstable'
    return {'depth':float(depths[k]), 'index':k, 'views':int(count[k]), 'view_indices':used.tolist(), 'score':float(avg[k]), 'margin':float(avg[k]-np.max(competition))}, None



def match_pixel(gray, refmask, pose, target, px, py, depths):
    """Match one observed patch at constant radial depth against other ERP cameras."""
    R,C=pose; offsets=np.arange(-3,4); dx,dy=np.meshgrid(offsets,offsets)
    patch,valid=sample(gray,refmask,px+dx,py+dy)
    if not valid.all() or np.std(patch)<.03:
        return None, 'reference_mask_or_low_texture'
    bearing=rays(px+dx,py+dy,1024,512)@R; values=np.full((len(target),len(depths)),-2.)
    for vi,(image,mask,(Rt,Ct)) in enumerate(target):
        for j,depth in enumerate(depths):
            world=C+bearing*depth;xx,yy,dist=project(world,Rt,Ct,1024,512);p,ok=sample(image,mask,xx,yy)
            angle=np.degrees(np.arccos(np.clip(np.dot((world[3,3]-C)/depth,(world[3,3]-Ct)/dist[3,3]),-1,1)))
            if ok.all() and angle>=.2 and np.std(p)>=.03:
                a=patch-patch.mean();b=p-p.mean();values[vi,j]=float(np.sum(a*b)/np.sqrt(np.sum(a*a)*np.sum(b*b)))
    result,reason=select_depth(values,depths)
    if result is not None:
        centers=[target[v][2][1] for v in result['view_indices']]; baselines=[np.linalg.norm(c-C) for c in centers]
        separation=max(np.linalg.norm(a-b) for a in centers for b in centers)
        if separation < .1 * max(baselines): return None, 'insufficient_viewpoint_diversity'
        result['leave_one_out_checked'] = result['views'] >= 3
    return result,reason


def hash_file(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('prepared', type=Path);parser.add_argument('model',type=Path);parser.add_argument('output',type=Path)
    parser.add_argument('--reference',type=int,required=True);parser.add_argument('--neighbors',type=int,nargs='+',required=True)
    parser.add_argument('--roi',type=int,nargs=4,required=True,metavar=('X','Y','W','H'))
    parser.add_argument('--stride',type=int,default=8);parser.add_argument('--samples',type=int,default=48);parser.add_argument('--timeout',type=int,default=240)
    args=parser.parse_args();started=time.monotonic()
    if len(args.neighbors)<2 or len(set(args.neighbors))!=len(args.neighbors) or args.reference in args.neighbors or args.stride<2 or args.samples<8:parser.error('Require at least two unique neighbors distinct from the reference and valid sampling')
    if args.output.exists():raise FileExistsError(args.output)
    manifest=json.loads((args.prepared/'manifest.json').read_text()); frames={r['source_frame']:r for r in manifest['frames'] if r['lens']=='cam0'}
    requested=[args.reference,*args.neighbors]
    if any(t not in frames or frames[t]['split']!='train' or frames[t]['name'] in manifest['heldout_evaluation_order'] for t in requested):raise ValueError('All captures must be training, not held out')
    poses=rig.read_poses(args.model); obs=modelio.observations(args.model/'images.bin'); points=modelio.points(args.model/'points3D.bin')
    def open_frame(frame):
        r=frames[frame];path=args.prepared/'images'/r['name'];mp=args.prepared/'masks'/r['name'];image=cv2.imread(str(path));mask=cv2.imread(str(mp),0)
        if image is None or mask is None or image.shape!=(512,1024,3) or mask.shape!=(512,1024):raise ValueError('Invalid images or masks')
        return image,mask,poses[r['source_name']],{'name':r['name'],'source_name':r['source_name'],'pts_microseconds':r['timestamp_microseconds'],'image_sha256':hash_file(path),'mask_sha256':hash_file(mp)}
    ref,refmask,(R,C),meta=open_frame(args.reference); neighbors=[open_frame(t) for t in args.neighbors]
    x,y,w,h=args.roi
    if min(x,y)<0 or w<8 or h<8 or x+w>1024 or y+h>512:raise ValueError('Invalid ROI')
    # Expand only for range estimation; a wider bound than measured points is still not a scene guarantee.
    depths=[]
    for (px,py),pid in obs[frames[args.reference]['source_name']].items():
        if x-80<=px<x+w+80 and y-80<=py<y+h+80 and pid in points:
            ix=int(round(px))%1024;iy=int(round(py))
            if 0<=iy<512 and refmask[iy,ix]==255:depths.append(np.linalg.norm(points[pid]-C))
    if len(depths)<8:raise ValueError('Too few neighboring reconstructed points to establish depth search range')
    lo,hi=np.percentile(depths,[5,95]);lo*=.8;hi*=1.25
    if not 0<lo<hi:raise ValueError('Invalid depth bounds')
    ds=1/np.linspace(1/hi,1/lo,args.samples);gray=cv2.cvtColor(ref,cv2.COLOR_BGR2GRAY).astype(np.float32)/255
    target=[(cv2.cvtColor(im,cv2.COLOR_BGR2GRAY).astype(np.float32)/255,mask,pose) for im,mask,pose,_ in neighbors]
    offsets=np.arange(-3,4);dx,dy=np.meshgrid(offsets,offsets);records=[];overlay=ref.copy();reasons={}
    for py in range(y+3,y+h-3,args.stride):
      for px in range(x+3,x+w-3,args.stride):
        if time.monotonic()-started>args.timeout:raise TimeoutError('CPU time limit reached')
        result,reason=match_pixel(gray,refmask,(R,C),target,px,py,ds)
        if reason:reasons[reason]=reasons.get(reason,0)+1;cv2.circle(overlay,(px,py),1,(0,0,255),-1)
        else:records.append({'xy':[px,py],**result});cv2.circle(overlay,(px,py),2,(0,255,0),-1)
    args.output.mkdir(parents=True);cv2.rectangle(overlay,(x,y),(x+w-1,y+h-1),(255,255,0),1);cv2.imwrite(str(args.output/'overlay.png'),overlay)
    result={'method':'Native ERP local constant radial depth patches, training images only; original model was reconstructed using all frames including heldouts, so camera poses and depth bounds are not independent of heldout information. Nearby model observations set expanded 5th/95th percentile depth bounds. Independent matching views and peak uniqueness are required. Green points are hypothesis-support diagnostics, not independently verified geometry or seed points.','reference':meta,'neighbors':[v[3] for v in neighbors],'model_images_sha256':hash_file(args.model/'images.bin'),'model_points_sha256':hash_file(args.model/'points3D.bin'),'roi_xywh':args.roi,'depth_bounds': [float(lo),float(hi)],'bounds_points':len(depths),'sample_count':args.samples,'stride':args.stride,'minimum_ncc':0.8,'peak_margin':0.05,'minimum_parallax_degrees':0.2,'patch_size':7,'minimum_source_std':0.03,'minimum_neighbor_views':2,'note':'Leave-one-out is checked only for candidates supported by at least three neighbors; other candidates pass individual-view peak checks and viewpoint diversity only. Constant radial depth is a local approximation.','script_sha256':hash_file(Path(__file__)),'rejections':reasons,'accepted':records,'elapsed_seconds':time.monotonic()-started,'overlay_sha256':hash_file(args.output/'overlay.png')}
    (args.output/'report.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n');print(json.dumps({'accepted':len(records),'rejections':reasons,'elapsed_seconds':result['elapsed_seconds']},indent=2))
if __name__=='__main__':main()
