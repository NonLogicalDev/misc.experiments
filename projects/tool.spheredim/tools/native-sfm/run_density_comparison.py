#!/usr/bin/env python3
"""Compare temporal-only fixed-rig SfM at two reviewed sampling densities."""
import argparse
import csv
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

import compare_rigs
import build_rig_pair_graph as graph
import run_rig_pair as rig

RESERVE=35*1024**3
LIMIT=150*1024**2
TIMEOUT=300


def read_priors(path):
    with path.open(newline='') as f:
        rows=list(csv.DictReader(f))
    by_name={row['image']:row for row in rows}
    if len(by_name)!=len(rows):raise ValueError('Duplicate prior image')
    return by_name


def preflight(binary, baseline, dense):
    binary,baseline,dense=(Path(x).resolve(strict=True) for x in (binary,baseline,dense))
    low=json.loads((baseline/'manifest.json').read_text());high=json.loads((dense/'manifest.json').read_text())
    lo={f['source_frame']:f for f in low['frames']};hi={f['source_frame']:f for f in high['frames']}
    if len(lo)!=138 or len(hi)!=412 or len(lo)!=len(low['frames']) or len(hi)!=len(high['frames']) or not lo.keys() <= hi.keys():raise ValueError('Expected 138 distinct baseline frames shared by 412 distinct dense frames')
    if low['resolution']!=high['resolution'] or low['resolution']!=[1024,512]:raise ValueError('Unexpected or mismatched resolution')
    cfg0=baseline/'rig-metadata.json';cfg1=dense/'rig-metadata.json'
    if rig.digest(cfg0)!=rig.digest(cfg1):raise ValueError('Rig configs differ')
    p0=read_priors(baseline/'rotation-priors.csv');p1=read_priors(dense/'rotation-priors.csv')
    shared={f'cam{j}/frame_{frame:06d}.png' for frame in lo for j in (0,1)}
    expected_high={f'cam{j}/frame_{frame:06d}.png' for frame in hi for j in (0,1)}
    if set(p0)!=shared or set(p1)!=expected_high or any(p0[n]!=p1[n] for n in shared):raise ValueError('Prior inventory or shared rows differ')
    hashes={}
    for frame in sorted(lo):
        if lo[frame]['timestamp_microseconds']!=hi[frame]['timestamp_microseconds'] or lo[frame]['source_packet_pts']!=hi[frame]['source_packet_pts']:raise ValueError(f'Timestamp mismatch: {frame}')
        for lens in ('cam0','cam1'):
            name=f'{lens}/frame_{frame:06d}.png';hashes[name]={}
            for folder,key in (('images','image_sha256'),('masks','mask_sha256'),('feature-masks','feature_mask_sha256')):
                a=rig.digest(baseline/folder/name);b=rig.digest(dense/folder/name)
                if a!=b or a!=lo[frame]['lenses'][lens][key] or b!=hi[frame]['lenses'][lens][key]:raise ValueError(f'Shared {folder} mismatch: {name}')
                hashes[name][folder]=a
    return {'binary_sha256':rig.digest(binary),'baseline_manifest_sha256':rig.digest(baseline/'manifest.json'),
            'dense_manifest_sha256':rig.digest(dense/'manifest.json'),'rig_sha256':rig.digest(cfg0),
            'baseline_priors_sha256':rig.digest(baseline/'rotation-priors.csv'),'dense_priors_sha256':rig.digest(dense/'rotation-priors.csv'),
            'shared_input_sha256':hashes,'baseline_frames':len(lo),'dense_frames':len(hi)}


def validate_graph(baseline,dense,pairdir):
    manifest=json.loads((pairdir/'manifest.json').read_text())
    if manifest['baseline_manifest_sha256']!=rig.digest(baseline/'manifest.json') or manifest['dense_manifest_sha256']!=rig.digest(dense/'manifest.json'):
        raise ValueError('Pair graph manifests differ from datasets')
    lo=graph.frames(baseline/'manifest.json');hi=graph.frames(dense/'manifest.json')
    base,combined,_,_=graph.build_graphs(list(lo),list(hi),manifest['overlap'],manifest['sync_pairs'])
    for name,expected in (('baseline',base),('dense',combined)):
        data=''.join(f'{a}\t{b}\n' for a,b in sorted(expected)).encode()
        file=pairdir/f'{name}.tsv'
        if file.read_bytes()!=data or rig.digest(file)!=manifest[f'{name}_pairs_sha256']:
            raise ValueError(f'Pair file does not match declared graph: {name}')
    return {'baseline_count':len(base),'dense_count':len(combined),
            'baseline_sha256':rig.digest(pairdir/'baseline.tsv'),'dense_sha256':rig.digest(pairdir/'dense.tsv')}


def command(binary,dataset,work,pairs):
    cmd=rig.command(binary,dataset,work,dataset/'rig-metadata.json',True,'float')
    return cmd+['--pairs-file',str(pairs),'--rotation-priors',str(dataset/'rotation-priors.csv')]


def stop(proc):
    if proc.poll() is None:
        os.killpg(proc.pid,signal.SIGTERM)
        try:proc.wait(timeout=10)
        except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait()


def run(binary,baseline,dense,pairdir,output,arm):
    binary,baseline,dense,pairdir=(Path(x).resolve(strict=True) for x in (binary,baseline,dense,pairdir));output=Path(output).resolve()
    if output.exists() or shutil.disk_usage(output.parent).free<RESERVE+LIMIT:raise ValueError('Output exists or reserve plus output budget unavailable')
    inputs=preflight(binary,baseline,dense);pairs=validate_graph(baseline,dense,pairdir);output.mkdir()
    env={k:v for k,v in os.environ.items() if not k.startswith('SS_SFM_')};env.update(SS_SFM_PIXEL_CENTER='0',SS_LANG='en')
    dataset,expected=(baseline,276) if arm=='baseline' else (dense,824)
    work=output/'workspace';work.mkdir();cmd=command(binary,dataset,work,pairdir/f'{arm}.tsv')
    rec={'method':'Explicit graph preserves all 138-body exhaustive candidates plus dense temporal and synchronized pairs; prior factor count changes with density.',
         'inputs':inputs,'pairs':pairs,'arm':arm,'command':cmd,'environment':{'SS_SFM_PIXEL_CENTER':'0','SS_LANG':'en'},
         'timeout_seconds':TIMEOUT,'max_output_bytes':LIMIT,'min_free_bytes':RESERVE,'status':'running'}
    rig.publish(output/'manifest.json',rec);start=time.monotonic();reason=None
    with (work/'run.log').open('wb') as log:
        proc=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,env=env)
        try:
            while proc.poll() is None:
                if time.monotonic()-start>TIMEOUT:reason='time limit exceeded'
                elif rig.size(work)>LIMIT:reason='output limit exceeded'
                elif shutil.disk_usage(output).free<RESERVE:reason='free-space reserve violated'
                if reason:stop(proc);break
                time.sleep(1)
        finally:stop(proc)
    if reason is None and rig.size(work)>LIMIT:reason='output limit exceeded'
    if reason is None and shutil.disk_usage(output).free<RESERVE:reason='free-space reserve violated'
    models=sorted(p for p in (work/'sparse').glob('*') if p.is_dir() and p.name.isdigit());pose_sets=[set(compare_rigs.read_poses(p)) for p in models];counts=[len(x) for x in pose_sets]
    frames=json.loads((dataset/'manifest.json').read_text())['frames'];expected_names={f"cam{j}/frame_{f['source_frame']:06d}.png" for f in frames for j in (0,1)}
    inventory_ok=len(expected_names)==expected and len(pose_sets)==1 and pose_sets[0]==expected_names
    rec.update(elapsed_seconds=time.monotonic()-start,exit_code=proc.returncode,output_bytes=rig.size(work),model_image_counts=counts,inventory_exact=inventory_ok,
               status='complete' if not reason and proc.returncode==0 and inventory_ok else 'failed',error=reason)
    rig.publish(output/'manifest.json',rec)
    if rec['status']!='complete':raise RuntimeError(f'{arm} did not produce one connected model with {expected} images; see manifest and log')
    return rec


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('binary',type=Path);p.add_argument('baseline',type=Path);p.add_argument('dense',type=Path);p.add_argument('pairdir',type=Path);p.add_argument('output',type=Path);p.add_argument('--arm',choices=('baseline','dense'),required=True);p.add_argument('--preflight-only',action='store_true');a=p.parse_args()
    if a.preflight_only:
        preflight(a.binary,a.baseline,a.dense);print(json.dumps(validate_graph(a.baseline,a.dense,a.pairdir),indent=2))
    else:run(a.binary,a.baseline,a.dense,a.pairdir,a.output,a.arm)
if __name__=='__main__':main()
