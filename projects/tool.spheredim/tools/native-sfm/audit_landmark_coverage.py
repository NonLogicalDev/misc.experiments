#!/usr/bin/env python3
"""Audit original SfM landmark support under a selected set of paired timestamps."""
import argparse
import csv
import gzip
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
from scipy.spatial.distance import pdist
import compare_density_models as modelio
import compare_rigs
import prepare_splat


def measure(point, observations, chosen):
    """Count timestamp views separately from physical-lens observations."""
    retained=[v for v in observations if v[0] in chosen]
    bytime={};pairs=defaultdict(set)
    for frame,lens,center in retained:
        bytime.setdefault(frame,center);pairs[frame].add(lens)
    centers=np.asarray(list(bytime.values()),dtype=float).reshape(-1,3)
    result={'observations':len(retained),'timestamps':len(bytime),'stereo_timestamps':sum(len(v)==2 for v in pairs.values()),'max_baseline':None,'max_view_angle_degrees':None}
    if len(centers)>=2:
        result['max_baseline']=float(np.max(pdist(centers)))
        rays=point-centers;norm=np.linalg.norm(rays,axis=1)
        if np.any(norm<1e-12):raise ValueError('Landmark coincides with camera center')
        result['max_view_angle_degrees']=float(np.degrees(np.arccos(np.clip(1-np.max(pdist(rays/norm[:,None],metric='cosine')),-1,1))))
    return result


def summary(rows):
    hist=defaultdict(int)
    for row in rows:hist[str(min(row['timestamps'],5))+'+' if row['timestamps']>=5 else str(row['timestamps'])]+=1
    def quantile(key):
        values=[r[key] for r in rows if r[key] is not None]
        return None if not values else {'median':float(np.median(values)),'p10':float(np.percentile(values,10)),'p90':float(np.percentile(values,90))}
    return {'landmarks':len(rows),'timestamp_count_histogram_5_plus':dict(sorted(hist.items())),'at_least_two_timestamps':sum(r['timestamps']>=2 for r in rows),'stereo_at_any_timestamp':sum(r['stereo_timestamps']>0 for r in rows),'max_baseline_scene_units':quantile('max_baseline'),'max_view_angle_degrees':quantile('max_view_angle_degrees')}


def audit(model,prepared,selected,output):
    model=Path(model).resolve(strict=True);prepared=Path(prepared).resolve(strict=True);selected=Path(selected).resolve(strict=True);output=Path(output).resolve()
    if output.exists():raise FileExistsError(output)
    manifest=json.loads((prepared/'manifest.json').read_text());selection=json.loads(selected.read_text())
    source=Path(manifest['dataset']).resolve(strict=True);source_manifest=source/'manifest.json'
    if prepare_splat.digest(source_manifest)!=manifest['source_manifest_sha256']:raise ValueError('Source manifest mismatch')
    source_frames={f['source_frame']:f for f in json.loads(source_manifest.read_text())['frames']}
    frames=manifest['frames'];train={f['source_frame'] for f in frames if f['split']=='train'};held={f['source_frame'] for f in frames if f['split']=='eval'}
    if train&held or any({x['split'] for x in frames if x['source_frame']==n} not in ({'train'},{'eval'}) for n in train|held):raise ValueError('Physical pair split mismatch')
    chosen=set(selection['selected_indices'])&train
    if not chosen or not chosen<=train:raise ValueError('Empty or invalid selected set')
    lookup={f['source_name']:f for f in frames if f['split']=='train'}
    positions=compare_rigs.read_poses(model);observations=modelio.observations(model/'images.bin');points=modelio.points(model/'points3D.bin')
    if set(lookup)-positions.keys() or set(lookup)-observations.keys():raise ValueError('Missing original training poses or observations')
    tracks=defaultdict(list);frame_tracks=defaultdict(set);masked=0;accepted=0
    for name,f in lookup.items():
        mask_path=prepared/'masks'/f['name']
        if prepare_splat.digest(mask_path)!=source_frames[f['source_frame']]['lenses'][f['lens']]['mask_sha256']:raise ValueError(f'Training mask hash mismatch: {name}')
        mask=cv2.imread(str(mask_path),cv2.IMREAD_GRAYSCALE)
        if mask is None or mask.shape!=(512,1024):raise ValueError(f'Invalid training mask: {name}')
        for (x,y),pid in observations[name].items():
            ix,iy=int(round(x)),int(round(y))
            if not (0<=ix<1024 and 0<=iy<512) or mask[iy,ix]!=255:masked+=1;continue
            if pid not in points:raise ValueError('Observation references missing landmark')
            tracks[pid].append((f['source_frame'],f['lens'],positions[name][1]));frame_tracks[f['source_frame']].add(pid);accepted+=1
    ids=sorted(points);xyz=np.stack([points[i] for i in ids]);edges=[np.quantile(xyz[:,i],[.25,.5,.75]) for i in range(3)]
    full=[];subset=[];bins=defaultdict(lambda: {'landmarks':0,'lost_all':0,'lost_multiview':0})
    output.mkdir();csv_path=output/'per-landmark.csv.gz'
    with gzip.open(csv_path,'wt',newline='') as f:
        w=csv.writer(f);w.writerow(['landmark_id','full_observations','selected_observations','full_timestamps','selected_timestamps','full_stereo_timestamps','selected_stereo_timestamps','full_max_baseline','selected_max_baseline','full_max_view_angle_degrees','selected_max_view_angle_degrees','spatial_bin'])
        for pid,point in zip(ids,xyz):
            a=measure(point,tracks[pid],train);b=measure(point,tracks[pid],chosen);full.append(a);subset.append(b)
            cell=tuple(int(np.searchsorted(edges[i],point[i],side='right')) for i in range(3));key=','.join(map(str,cell));q=bins[key];q['landmarks']+=1;q['lost_all']+=b['timestamps']==0;q['lost_multiview']+=a['timestamps']>=2 and b['timestamps']<2
            w.writerow([pid,a['observations'],b['observations'],a['timestamps'],b['timestamps'],a['stereo_timestamps'],b['stereo_timestamps'],a['max_baseline'],b['max_baseline'],a['max_view_angle_degrees'],b['max_view_angle_degrees'],key])
    def connectivity(frameset):
        ordered=sorted(frameset); links=[len(frame_tracks[a]&frame_tracks[b]) for a,b in zip(ordered,ordered[1:])]
        return {'transitions':len(links),'zero_shared_tracks':sum(x==0 for x in links),'fewer_than_5_shared_tracks':sum(x<5 for x in links),'fewer_than_20_shared_tracks':sum(x<20 for x in links),'median_shared_tracks':float(np.median(links)) if links else None,'minimum_shared_tracks':min(links) if links else None}
    data={'connectivity_note':'Counts of mask-valid original SfM track IDs shared between consecutive selected timestamps; thresholds 5 and 20 are descriptive diagnostics, not verified connectivity requirements.', 'connectivity':{'full_training':connectivity(train),'selected_training':connectivity(chosen)}, 'model_landmarks':len(points),'landmarks_with_training_observation':len([p for p in ids if tracks[p]]), 'method':'Original SfM keypoint tracks filtered at each original dense-training keep mask. Evaluation timestamps are excluded from both groups. A camera-center representative is used per timestamp for max baseline and ray angle; two physical lenses at the same timestamp count separately only in stereo and observation totals. 3D quantile bins describe reconstructed feature locations, not surface coverage. SfM points/poses are not ground truth and featureless surfaces remain unknown.','model':str(model),'prepared':str(prepared),'selection':str(selected),'sha256':{'images_bin':prepare_splat.digest(model/'images.bin'),'points_bin':prepare_splat.digest(model/'points3D.bin'),'prepared_manifest':prepare_splat.digest(prepared/'manifest.json'),'source_manifest':prepare_splat.digest(source_manifest),'selection':prepare_splat.digest(selected),'script':prepare_splat.digest(Path(__file__)),'per_landmark_csv_gz':prepare_splat.digest(csv_path)},'training_timestamps':len(train),'selected_training_timestamps':len(chosen),'heldout_timestamps':len(held),'accepted_feature_observations':accepted,'outside_training_mask_observations':masked,'full_training':summary(full),'selected_training':summary(subset),'quantile_bin_edges':[[float(v) for v in e] for e in edges],'spatial_bins':dict(sorted(bins.items()))}
    raw=(json.dumps(data,indent=2,allow_nan=False)+'\n').encode();(output/'audit.json').write_bytes(raw)
    if len(raw)+csv_path.stat().st_size>5*1024**2:raise ValueError('Audit exceeds 5 MiB output budget')
    return data


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('model',type=Path);p.add_argument('prepared',type=Path);p.add_argument('selection',type=Path);p.add_argument('output',type=Path);a=p.parse_args();d=audit(a.model,a.prepared,a.selection,a.output);print(json.dumps({k:d[k] for k in ('training_timestamps','selected_training_timestamps','heldout_timestamps','full_training','selected_training')},indent=2))


if __name__=='__main__':main()
