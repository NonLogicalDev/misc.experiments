#!/usr/bin/env python3
"""Build reproducible explicit pair lists for matched two-lens density trials."""
import argparse
import hashlib
import itertools
import json
from pathlib import Path


def names(frames):
    return [f'cam{lens}/frame_{frame:06d}.png' for lens in (0,1) for frame in frames]


def build_graphs(shared, dense, overlap=10, sync_pairs=False):
    if len(shared)<2 or len(set(shared))!=len(shared) or len(set(dense))!=len(dense) or not set(shared)<=set(dense) or overlap<1:
        raise ValueError('Expected distinct shared frames contained in dense frames and positive overlap')
    shared=sorted(shared);dense=sorted(dense)
    baseline=set(itertools.combinations(names(shared),2));temporal=set();sync=set()
    for lens in (0,1):
        sequence=[f'cam{lens}/frame_{frame:06d}.png' for frame in dense]
        for i,name in enumerate(sequence):
            offsets=set(range(1,overlap+1))|{1<<k for k in range(overlap)}
            for offset in offsets:
                if i+offset<len(sequence):temporal.add(tuple(sorted((name,sequence[i+offset]))))
    if sync_pairs:
        sync={(f'cam0/frame_{frame:06d}.png',f'cam1/frame_{frame:06d}.png') for frame in dense}
    return baseline, baseline|temporal|sync, temporal, sync


def frames(path):
    data=json.loads(path.read_text());rows=data['frames'];result={r['source_frame']:r for r in rows}
    if len(result)!=len(rows):raise ValueError('Duplicate frame in manifest')
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('baseline_manifest',type=Path);p.add_argument('dense_manifest',type=Path);p.add_argument('output',type=Path);p.add_argument('--overlap',type=int,default=10);p.add_argument('--sync-pairs',action='store_true');a=p.parse_args()
    low=frames(a.baseline_manifest);high=frames(a.dense_manifest)
    if not low.keys()<=high.keys():raise ValueError('Dense set omits baseline frames')
    for frame in low:
        if low[frame]['timestamp_microseconds']!=high[frame]['timestamp_microseconds'] or low[frame]['source_packet_pts']!=high[frame]['source_packet_pts']:raise ValueError(f'PTS mismatch: {frame}')
    base,combined,temporal,sync=build_graphs(list(low),list(high),a.overlap,a.sync_pairs)
    if a.output.exists():raise FileExistsError(a.output)
    a.output.mkdir()
    def write(name,pairs):
        data=''.join(f'{x}\t{y}\n' for x,y in sorted(pairs)).encode();(a.output/name).write_bytes(data);return hashlib.sha256(data).hexdigest()
    report={'baseline_manifest_sha256':hashlib.sha256(a.baseline_manifest.read_bytes()).hexdigest(),'dense_manifest_sha256':hashlib.sha256(a.dense_manifest.read_bytes()).hexdigest(),'baseline_frames':len(low),'dense_frames':len(high),'overlap':a.overlap,'sync_pairs':a.sync_pairs,'baseline_pairs':len(base),'temporal_pairs':len(temporal),'sync_pair_candidates':len(sync),'additional_temporal_pairs':len(temporal-base),'additional_sync_pairs':len(sync-(base|temporal)),'dense_union_pairs':len(combined),'baseline_pairs_sha256':write('baseline.tsv',base),'dense_pairs_sha256':write('dense.tsv',combined)}
    (a.output/'manifest.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
