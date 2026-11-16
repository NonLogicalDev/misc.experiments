#!/usr/bin/env python3
"""Compare own-gauge poster-region SfM residuals on source-defined pixels."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import time
import cv2
import numpy as np
import compare_density_models as io
import compare_rigs as rig
import audit_seed_gauge as gauge

ROI=(450,440,250,250)
FRAMES=(1440,1495,1500,1505,1560)


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()


def cell(xy):
    x,y,w,h=ROI
    return min(3,int((xy[0]-x)*4/w)),min(3,int((xy[1]-y)*4/h))


def audit(model,width,frames,prepared,deadline):
    poses=rig.read_binary_poses(model/'images.bin');observations=io.observations(model/'images.bin');points=io.points(model/'points3D.bin');reference='cam0/frame_001500.png';refrow=frames[reference];mask=cv2.imread(str(prepared/'masks'/refrow['name']),0)
    if mask is None or mask.shape!=(1024,2048):raise ValueError('Invalid reference mask')
    x,y,w,h=ROI;selected={}
    for xy,pid in observations[reference].items():
        u,v=np.array(xy)*2048/width;ix=int(round(u));iy=int(round(v))
        if x<=u<x+w and y<=v<y+h and 0<=ix<2048 and 0<=iy<1024 and mask[iy,ix]==255 and pid in points:selected[pid]=(float(u),float(v))
    tracks=defaultdict(set);seen={n:{} for n in FRAMES};mask_hashes={}
    for name,row in frames.items():
        if time.monotonic()>deadline:raise TimeoutError('CPU deadline')
        frame=row['source_frame']
        if not (row['split']=='train' and 1320<=frame<=1530) and not (name.startswith('cam0/') and frame in FRAMES):continue
        path=prepared/'masks'/row['name'];mask=cv2.imread(str(path),0)
        if mask is None or mask.shape!=(1024,2048):raise ValueError('Invalid native mask')
        mask_hashes[row['name']]=sha(path)
        for xy,pid in observations[name].items():
            if pid not in selected:continue
            u,v=np.array(xy)*2048/width;ix=int(round(u));iy=int(round(v))
            if 0<=ix<2048 and 0<=iy<1024 and mask[iy,ix]==255:
                if row['split']=='train' and 1320<=frame<=1530:tracks[pid].add(frame)
                if name.startswith('cam0/') and frame in FRAMES:
                    if pid in seen[frame]:raise ValueError('Duplicate point observation in one image')
                    seen[frame][pid]=xy
    supported={pid for pid in selected if len(tracks[pid])>=3};views={}
    for frame,entries in seen.items():
        ids=sorted(supported & entries.keys());pose=poses[f'cam0/frame_{frame:06}.png'];errs=gauge.angular_errors(np.array([points[i] for i in ids]).reshape(-1,3),*pose,np.array([entries[i] for i in ids]).reshape(-1,2),width)*2 if ids else np.array([])
        views[str(frame)]={'supported_landmarks_observed':len(ids),'reference_grid_4x4_cells':sorted({f'{cell(selected[i])[0]},{cell(selected[i])[1]}' for i in ids}),'target_image_grid_16x8_cells':sorted({f'{min(15,int(entries[i][0]*2048/width)//128)},{min(7,int(entries[i][1]*2048/width)//128)}' for i in ids}),'angular_error_native2048_px_p50_p90':np.percentile(errs,[50,90]).tolist() if len(errs) else None,'observations':[{'point_id':int(pid),'reference_xy_native':selected[pid],'target_feature_xy_native':(np.array(entries[pid])*2048/width).tolist(),'error_native2048_angular_px':float(err)} for pid,err in zip(ids,errs)]}
    common=set.intersection(*(supported & set(entries) for entries in seen.values()))
    return {'roi_observed_points':len(selected),'supported_at_three_training_timestamps':len(supported),'reference_grid_4x4_cells':sorted({f'{cell(selected[i])[0]},{cell(selected[i])[1]}' for i in supported}),'in_all_five_frames_count':len(common),'in_all_five_point_ids':sorted(map(int,common)),'views':views},mask_hashes


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('original',type=Path);p.add_argument('native_prepared',type=Path);p.add_argument('original_prepared',type=Path);p.add_argument('output',type=Path);a=p.parse_args();deadline=time.monotonic()+55
    if a.output.exists():raise FileExistsError(a.output)
    hi=json.loads((a.native_prepared/'manifest.json').read_text());lo=json.loads((a.original_prepared/'manifest.json').read_text());native=Path(hi['model']);frames={r['source_name']:r for r in hi['frames']};low={r['source_name']:r for r in lo['frames']}
    if len(frames)!=len(hi['frames']) or set(frames)!=set(low):raise ValueError('Capture manifest mismatch')
    for name in frames:
        for key in ('source_frame','lens','timestamp_microseconds','source_packet_pts','split'):
            if frames[name][key]!=low[name][key]:raise ValueError(f'Capture identity mismatch: {name}')
    for name,expected in hi['model_hashes'].items():
        if name in ('cameras.bin','images.bin','points3D.bin') and sha(native/name)!=expected:raise ValueError('Native model provenance mismatch')
    gauge.validate_2x_cameras(gauge.read_erp_cameras(a.original/'cameras.bin'),gauge.read_erp_cameras(native/'cameras.bin'))
    input_hashes={}
    for frame in FRAMES:
        row=frames[f'cam0/frame_{frame:06}.png'];src=a.native_prepared/'images'/row['name'];mask=a.native_prepared/'masks'/row['name'];other=a.original_prepared/'images'/low[row['source_name']]['name'];othermask=a.original_prepared/'masks'/low[row['source_name']]['name']
        if sha(src)!=sha(other) or sha(mask)!=sha(othermask):raise ValueError(f'Source pixels or mask differ: {frame}')
        input_hashes[str(frame)]={'image':sha(src),'mask':sha(mask)}
    baseline,ma=audit(a.original,1024,frames,a.native_prepared,deadline);candidate,mb=audit(native,2048,frames,a.native_prepared,deadline)
    if ma!=mb:raise ValueError('Mask provenance mismatch')
    report={'method':'Same source-defined native2048 frame1500 rectangle, full-sphere cameras and exact same source captures/masks. Each model uses its own 1500-observed landmark population, own original poses and point positions; point IDs across models are unrelated. Only points supported by at least three distinct training timestamps in 1320–1530 are scored. 1440/1560 are held out from splat training but entered SfM. Angular residuals are converted to 2048-equivalent pixels, not raw xy differences; matching and reprojection are in-sample, so they do not establish pose accuracy. Reference grid cells describe frame1500, not target-view image coverage.','roi_xywh':ROI,'source_capture_sha256':input_hashes,'training_masks_sha256':ma,'original_model_sha256':{n:sha(a.original/n) for n in ('cameras.bin','images.bin','points3D.bin')},'native_model_sha256':{n:sha(native/n) for n in ('cameras.bin','images.bin','points3D.bin')},'original_manifest_sha256':sha(a.original_prepared/'manifest.json'),'native_manifest_sha256':sha(a.native_prepared/'manifest.json'),'script_sha256':sha(Path(__file__)),'original':baseline,'native':candidate}
    text=json.dumps(report,indent=2,allow_nan=False)+'\n'
    if len(text.encode())>1000000:raise ValueError('Output exceeds 1 MB')
    a.output.write_text(text);print(json.dumps({k:{'supported':v['supported_at_three_training_timestamps'],'all_five':v['in_all_five_frames_count'],'views':{f:{'n':r['supported_landmarks_observed'],'p50_p90':r['angular_error_native2048_px_p50_p90']} for f,r in v['views'].items()}} for k,v in [('original',baseline),('native',candidate)]},indent=2))
if __name__=='__main__':main()
