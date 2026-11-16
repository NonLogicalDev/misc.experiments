#!/usr/bin/env python3
"""Prepare a dense rig splat trial with frozen eval views and reviewed mask overrides."""
import argparse
import copy
import json
import os
from pathlib import Path
import shutil

import cv2
import numpy as np
import prepare_splat as prep
import run_splat as runner

RESERVE=35*1024**3
RUN_BUDGET=512*1024**2


def validate_override(base, candidate, frame, lens, entry):
    name=f'frame_{frame:06d}.png';original=base/'masks'/lens/name;image=base/'images'/lens/name;replacement=candidate/'masks'/lens/name;overlay=candidate/'overlays'/name
    if lens!='cam0' or entry['frame']!=frame or entry['lens']!=lens:raise ValueError('Unexpected override identity')
    if prep.digest(image)!=entry['source_image_sha256'] or prep.digest(original)!=entry['source_mask_sha256'] or prep.digest(replacement)!=entry['override_mask_sha256'] or prep.digest(overlay)!=entry['overlay_sha256']:
        raise ValueError(f'Override provenance mismatch: {name}')
    old=cv2.imread(str(original),cv2.IMREAD_GRAYSCALE);new=cv2.imread(str(replacement),cv2.IMREAD_GRAYSCALE)
    if old is None or new is None or old.shape!=(512,1024) or new.shape!=old.shape or not np.isin(old,[0,255]).all() or not np.isin(new,[0,255]).all() or np.any((new==255)&(old!=255)):
        raise ValueError(f'Override must be a binary subset of the original keep mask: {name}')
    count=int(np.count_nonzero((old==255)&(new==0)))
    if count!=entry['newly_excluded_pixels'] or count==0:raise ValueError(f'Override exclusion count mismatch: {name}')
    return replacement


def prepare(dataset,model,binary,baseline_manifest,candidate,reviewed_sha,output):
    dataset,model,binary,baseline_manifest,candidate=(Path(p).resolve(strict=True) for p in (dataset,model,binary,baseline_manifest,candidate));output=Path(output).resolve()
    if output.exists() or shutil.disk_usage(output.parent).free<RESERVE+RUN_BUDGET:raise ValueError('Output exists or insufficient 35 GiB reserve plus 512 MiB run budget')
    source=json.loads((dataset/'manifest.json').read_text());baseline=json.loads(baseline_manifest.read_text());candidate_file=candidate/'manifest.json'
    if prep.digest(candidate_file)!=reviewed_sha:raise ValueError('Candidate manifest differs from reviewed hash')
    cm=json.loads(candidate_file.read_text())
    if cm['source_dataset_manifest_sha256']!=prep.digest(dataset/'manifest.json'):raise ValueError('Candidate is for another dataset')
    entries={(e['frame'],e['lens']):e for e in cm['entries']};expected={(n,'cam0') for n in range(2020,2056,5)}
    if set(entries)!=expected or len(entries)!=len(cm['entries']):raise ValueError('Expected exactly eight unique reviewed cam0 overrides')
    frame_ids=[f['source_frame'] for f in source['frames']]
    baseline_eval=sorted({f['source_frame'] for f in baseline['frames'] if f['split']=='eval'})
    original_names=baseline['heldout_evaluation_order'];split=prep.split_frames(frame_ids,24)
    if len(frame_ids)!=412 or len(baseline_eval)!=18 or sorted(k for k,v in split.items() if v=='eval')!=baseline_eval:
        raise ValueError('Dense split differs from the original 18 evaluation timestamps')
    expected_names=sorted(f'eval_{n:06d}_cam{j}.png' for n in baseline_eval for j in (0,1))
    if original_names!=expected_names:raise ValueError('Original evaluation mapping differs')
    byframe={f['source_frame']:f for f in source['frames']}
    if len(byframe)!=len(frame_ids):raise ValueError('Duplicate dense timestamp')
    overrides={k:validate_override(dataset,candidate,*k,e) for k,e in entries.items()}
    # Freeze original source pixels for every evaluated camera before creating outputs.
    eval_hashes={}
    for name in original_names:
        frame=int(name[5:11]);lens=name[-8:-4];dense=dataset/'images'/lens/f'frame_{frame:06d}.png';old=baseline_manifest.parent/'images'/name
        a,b=prep.digest(dense),prep.digest(old)
        if a!=b or a!=byframe[frame]['lenses'][lens]['image_sha256']:raise ValueError(f'Evaluation image mismatch: {name}')
        eval_hashes[name]=a
    output.mkdir();(output/'INCOMPLETE').write_text('Preparation not complete\n');derived=output/'source'
    for folder in ('images','masks'):
        for lens in ('cam0','cam1'):(derived/folder/lens).mkdir(parents=True)
    updated=copy.deepcopy(source)
    for row in updated['frames']:
        frame=row['source_frame']
        for lens in ('cam0','cam1'):
            name=f'frame_{frame:06d}.png';info=row['lenses'][lens]
            for folder,key in (('images','image_sha256'),('masks','mask_sha256')):
                original=dataset/folder/lens/name
                if prep.digest(original)!=info[key]:raise ValueError(f'Dataset input hash mismatch: {original}')
                dest=derived/folder/lens/name
                if folder=='masks' and (frame,lens) in overrides:
                    shutil.copyfile(overrides[(frame,lens)],dest);info[key]=prep.digest(dest)
                else:os.link(original,dest)
        if shutil.disk_usage(output).free<RESERVE:raise RuntimeError('Free-space reserve violated')
    updated['status']='Dense SfM inputs with eight reviewed training/evaluation mask overrides; SfM source unchanged'
    updated['training_mask_override']={'candidate_manifest_sha256':reviewed_sha,'source_manifest_sha256':prep.digest(dataset/'manifest.json'),'entries':[{'frame':n,'lens':lens,'source_mask_sha256':entries[(n,lens)]['source_mask_sha256'],'override_mask_sha256':entries[(n,lens)]['override_mask_sha256']} for n,lens in sorted(entries)]}
    (derived/'manifest.json').write_text(json.dumps(updated,indent=2)+'\n')
    m=prep.prepare(derived,model,binary,output/'prepared','run',24,6000,1000)
    if m['heldout_evaluation_order']!=original_names or len(m['frames'])!=824 or sum(f['split']=='train' for f in m['frames'])!=788:raise ValueError('Prepared split mismatch')
    command,run_path,train,evals,steps=runner.verify(output/'prepared/manifest.json')
    command+=['--refine-stop-iter','0','--refine-stop-num-iter','2000']
    plan={'status':'prepared for review; no training started','source_manifest_sha256':prep.digest(dataset/'manifest.json'),'override_manifest_sha256':reviewed_sha,'baseline_manifest_sha256':prep.digest(baseline_manifest),'baseline_eval_rgb_sha256':eval_hashes,'model_hashes':m['model_hashes'],'seed_sha256':m['seed_sha256'],'binary_sha256':m['binary_sha256'],'train_cameras':train,'eval_cameras':evals,'steps':steps,'command':command,'run_path':str(run_path),'run_limit_bytes':RUN_BUDGET,'free_reserve_bytes':RESERVE,'notes':['Eight masks apply only to this splat dataset; SfM inputs and poses remain unchanged.','Frame 2040 cam0 changes evaluation mask; score both baseline and candidate using the common revised mask.','Seed points came from SfM before these overrides and may include the distant person; no source-point filtering has been claimed.','Splat-heldout views contributed to SfM; these are not independent pose validation.']}
    (output/'plan.json').write_text(json.dumps(plan,indent=2)+'\n');(output/'INCOMPLETE').unlink();return plan


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('dataset','model','binary','baseline_manifest','candidate','output'):p.add_argument(name,type=Path)
    p.add_argument('--reviewed-sha256',required=True);a=p.parse_args();d=prepare(a.dataset,a.model,a.binary,a.baseline_manifest,a.candidate,a.reviewed_sha256,a.output);print(json.dumps({k:d[k] for k in ('train_cameras','eval_cameras','steps','seed_sha256','run_path')},indent=2))
if __name__=='__main__':main()
