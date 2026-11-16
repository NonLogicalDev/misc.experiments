#!/usr/bin/env python3
"""Select paired training observations while retaining original SfM track support."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import time

import cv2
import numpy as np
import audit_landmark_coverage as audit
import compare_density_models as modelio
import compare_rigs
import prepare_splat


def patch_detail(image, valid):
    gray=image.astype(np.float32);pixels=gray[valid]
    if len(pixels)<1024:raise ValueError('Insufficient valid source pixels')
    lo,hi=np.percentile(pixels,[5,95]);gray=np.clip((gray-lo)*255/max(hi-lo,10),0,255).astype(np.float32)
    gray=cv2.GaussianBlur(gray,(0,0),1)
    gx=cv2.Sobel(gray,cv2.CV_32F,1,0,ksize=3)/8;gy=cv2.Sobel(gray,cv2.CV_32F,0,1,ksize=3)/8
    detail=cv2.boxFilter(np.clip(np.maximum(gx*gx+gy*gy-4,0),0,400),-1,(11,11))
    keep=cv2.erode(valid.astype(np.uint8),np.ones((11,11),np.uint8),borderType=cv2.BORDER_CONSTANT,borderValue=0)>0
    return detail,keep


def edges_for_track(point, observations, threshold=.8):
    """Return alternative timestamp pairs retaining baseline and view spread."""
    centers={}
    for frame,lens,center in observations: centers.setdefault(frame,center)
    frames=sorted(centers); centers=np.stack([centers[f] for f in frames])
    rays=point-centers;norm=np.linalg.norm(rays,axis=1)
    if np.any(norm<1e-12):raise ValueError('Landmark coincides with camera center')
    rays=rays/norm[:,None]; a,b=np.triu_indices(len(frames),1)
    baselines=np.linalg.norm(centers[a]-centers[b],axis=1)
    angles=np.arccos(np.clip(np.sum(rays[a]*rays[b],axis=1),-1,1))
    pairs=[(frames[i],frames[j]) for i,j in zip(a,b)]
    return ({p for p,v in zip(pairs,baselines) if v>=threshold*baselines.max()},
            {p for p,v in zip(pairs,angles) if v>=threshold*angles.max()})


def prune(frames,tracks,points,qualities,min_shared=20,cap=None):
    """Remove low-quality timestamps only while robust tracks and links survive."""
    remaining=set(frames);frame_tracks=defaultdict(set);edges={};adj=defaultdict(set);support={}
    for pid,obs in tracks.items():
        for frame,_,_ in obs:frame_tracks[frame].add(pid)
        if len({frame for frame,_,_ in obs})<3:continue
        support[pid]={frame for frame,_,_ in obs}
        variants=edges_for_track(points[pid],obs);edges[pid]=[set(x) for x in variants]
        for frame,_,_ in obs:adj[frame].add(pid)
    pinned_by_exact_three=sum(any(len(support[pid])==3 for pid in adj[frame]) for frame in remaining)
    blocked={'landmark_support':0,'chronological_overlap':0};history=[];snapshot=sorted(remaining) if cap==len(remaining) else None
    while True:
        changed=False
        ordered_now=sorted(remaining)
        nearest_gap={n:min((n-ordered_now[i-1] if i else float('inf')),(ordered_now[i+1]-n if i+1<len(ordered_now) else float('inf'))) for i,n in enumerate(ordered_now)}
        for frame in sorted(remaining,key=lambda n:(qualities.get(n,.5),nearest_gap[n],n)):
            ordered=sorted(remaining);i=ordered.index(frame)
            if len(remaining)<=2:break
            if i>0 and i+1<len(ordered) and len(frame_tracks[ordered[i-1]] & frame_tracks[ordered[i+1]])<min_shared:
                blocked['chronological_overlap']+=1;continue
            if any(len(support[pid])-1<3 or any(not any(frame not in pair for pair in variants) for variants in edges[pid]) for pid in adj[frame]):
                blocked['landmark_support']+=1;continue
            remaining.remove(frame);history.append(frame);changed=True
            for pid in adj[frame]:
                support[pid].remove(frame)
                for variants in edges[pid]:variants.difference_update(p for p in tuple(variants) if frame in p)
            if cap is not None and len(remaining)==cap:snapshot=sorted(remaining)
        if not changed:break
    return sorted(remaining),snapshot,blocked,history,pinned_by_exact_three


def run(model,prepared,selected,output,cap):
    started=time.monotonic();model=Path(model).resolve(strict=True);prepared=Path(prepared).resolve(strict=True);selected=Path(selected).resolve(strict=True);output=Path(output).resolve()
    if output.exists():raise FileExistsError(output)
    m=json.loads((prepared/'manifest.json').read_text()); original=json.loads(selected.read_text())
    source=Path(m['dataset']).resolve(strict=True);source_manifest=source/'manifest.json'
    if prepare_splat.digest(source_manifest)!=m['source_manifest_sha256']:raise ValueError('Source manifest mismatch')
    source_frames={f['source_frame']:f for f in json.loads(source_manifest.read_text())['frames']}
    frames=m['frames'];training={f['source_frame'] for f in frames if f['split']=='train'};held={f['source_frame'] for f in frames if f['split']=='eval'}
    if training&held or not training or cap is not None and not 2<=cap<=len(training):raise ValueError('Invalid training split or cap')
    original_selected=set(original['selected_indices'])&training
    poses=compare_rigs.read_poses(model);observations=modelio.observations(model/'images.bin');points=modelio.points(model/'points3D.bin')
    tracks=defaultdict(list);patches=defaultdict(list)
    for f in frames:
        if f['split']!='train':continue
        name=f['source_name'];source_entry=source_frames[f['source_frame']]['lenses'][f['lens']]
        for folder,key in (('images','image_sha256'),('masks','mask_sha256')):
            if prepare_splat.digest(prepared/folder/f['name'])!=source_entry[key]:raise ValueError(f'Input hash mismatch: {name}')
        mask=cv2.imread(str(prepared/'masks'/f['name']),cv2.IMREAD_GRAYSCALE);image=cv2.imread(str(prepared/'images'/f['name']),cv2.IMREAD_GRAYSCALE)
        if mask is None or image is None or image.shape!=(512,1024) or mask.shape!=image.shape:raise ValueError(f'Missing source or mask {name}')
        valid=mask==255; detail,patch_valid=patch_detail(image,valid)
        for (x,y),pid in observations[name].items():
            ix,iy=int(round(x)),int(round(y))
            if not (0<=ix<1024 and 0<=iy<512) or not valid[iy,ix]:continue
            if pid not in points:raise ValueError('Missing point')
            tracks[pid].append((f['source_frame'],f['lens'],poses[name][1]))
            if patch_valid[iy,ix]: patches[pid].append((f['source_frame'],float(detail[iy,ix])))
    frame_quality=defaultdict(list)
    for pid,values in patches.items():
        peak=max(v for _,v in values)
        if len({f for f,_ in values})<2 or peak<1:continue
        for frame,value in values:frame_quality[frame].append(value/peak)
    qualities={f:float(np.median(frame_quality[f])) if frame_quality[f] else .5 for f in training}
    result,cap_result,blocked,removed,pinned=prune(training,tracks,points,qualities,20,cap)
    def report(chosen):
        rows=[audit.measure(points[p],obs,set(chosen)) for p,obs in tracks.items()]
        links=[];sets=defaultdict(set)
        for pid,obs in tracks.items():
            for frame,_,_ in obs:sets[frame].add(pid)
        for a,b in zip(chosen,chosen[1:]):links.append(len(sets[a]&sets[b]))
        return {'timestamp_count':len(chosen),'track_support':audit.summary(rows),'shared_track_links':{'minimum':min(links) if links else None,'under_20':sum(x<20 for x in links),'median':float(np.median(links)) if links else None}}
    def patch_quality(chosen):
        selected=set(chosen);relative=[];covered=0
        for values in patches.values():
            peak=max(value for _,value in values)
            if peak<1 or len({frame for frame,_ in values})<2:continue
            retained=[value/peak for frame,value in values if frame in selected]
            if retained:covered+=1;relative.extend(retained)
        return {'landmarks_with_measurable_retained_patches':covered,'patch_count':len(relative),'median_relative_detail':float(np.median(relative)) if relative else None,'p10_relative_detail':float(np.percentile(relative,10)) if relative else None}
    result_data={'patch_quality_note':'Same-landmark normalized patch gradients are a relative proxy; changes in viewpoint, scale, exposure and content can affect the score. Values cannot prove blur or visual fidelity.', 'patch_quality':{'full_training':patch_quality(training),'existing_selection':patch_quality(original_selected),'coverage_first':patch_quality(result)}, 'method':'Greedy removal from original paired training timestamps, preserving >=3 timestamps and >=80% of each original >=3-timestamp landmark maximum baseline and angle, plus >=20 shared original tracks between adjacent selected times. Experimental thresholds and greedy result are not physical coverage truth. Same-landmark contrast-normalized smoothed gradient patches rank removals only; viewpoint, scale, exposure and content can confound. Fixed heldouts excluded; featureless surfaces unknown.','config':{'robust_min_training_timestamps':3,'retained_timestamps_per_robust_landmark':3,'baseline_fraction':.8,'angle_fraction':.8,'minimum_shared_tracks':20,'optional_comparison_cap':cap,'max_output_bytes':5*1024**2},'model':str(model),'prepared':str(prepared),'input_selection':str(selected),'sha256':{'images_bin':prepare_splat.digest(model/'images.bin'),'points_bin':prepare_splat.digest(model/'points3D.bin'),'prepared_manifest':prepare_splat.digest(prepared/'manifest.json'),'selection':prepare_splat.digest(selected),'script':prepare_splat.digest(Path(__file__))},'heldout_timestamps':sorted(held),'selected_indices':result,'optional_cap_indices':cap_result,'optional_cap_reached':cap_result is not None,'initial_timestamps_pinned_by_exact_three_tracks':pinned,'selected_timestamps_microseconds':[next(f['timestamp_microseconds'] for f in frames if f['source_frame']==n) for n in result],'per_timestamp_relative_patch_quality':{str(n):qualities[n] if frame_quality[n] else None for n in sorted(training)},'age_tie_break':'Prefer removal of temporally closer timestamps only when relative patch quality ties; no hard minimum gap.','removed_indices':removed,'blocked_attempts':blocked,'quality_unknown_timestamps':sum(not frame_quality[f] for f in training),'full_training':report(sorted(training)),'existing_selection':report(sorted(original_selected)),'coverage_first':report(result),'optional_cap':report(cap_result) if cap_result else None,'elapsed_seconds':time.monotonic()-started}
    raw=(json.dumps(result_data,indent=2,allow_nan=False)+'\n').encode()
    if len(raw)>5*1024**2:raise RuntimeError('Report exceeds 5 MiB')
    output.write_bytes(raw);return result_data


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('model',type=Path);p.add_argument('prepared',type=Path);p.add_argument('selection',type=Path);p.add_argument('output',type=Path);p.add_argument('--compare-cap',type=int);a=p.parse_args();r=run(a.model,a.prepared,a.selection,a.output,a.compare_cap);print(json.dumps({k:r[k] for k in ('full_training','existing_selection','coverage_first','optional_cap_reached','elapsed_seconds')},indent=2))


if __name__=='__main__':main()
