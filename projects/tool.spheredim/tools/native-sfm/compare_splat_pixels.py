#!/usr/bin/env python3
"""Compare two saved splat runs on identical source pixels and common masks."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import cv2
import numpy as np


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path, grayscale=False):
    image=cv2.imread(str(path),cv2.IMREAD_GRAYSCALE if grayscale else cv2.IMREAD_COLOR)
    if image is None:raise ValueError(f'Cannot read {path}')
    return image


def score(reference, baseline, candidate, base_mask, new_mask):
    if reference.ndim!=3 or reference.shape[2]!=3 or baseline.shape!=reference.shape or candidate.shape!=reference.shape or base_mask.shape!=reference.shape[:2] or new_mask.shape!=base_mask.shape:
        raise ValueError('Image and mask dimensions differ')
    if reference.shape[1]!=2*reference.shape[0]:raise ValueError('Expected full 2:1 ERP images')
    keep=(base_mask>=128)&(new_mask>=128)
    if not keep.any():raise ValueError('No common valid source pixels')
    height=keep.shape[0]
    weights=keep*np.cos((np.arange(height)+.5-height/2)*np.pi/height)[:,None]
    area=float(weights.sum());count=int(keep.sum())
    row_area=np.cos((np.arange(height)+.5-height/2)*np.pi/height)[:,None]
    result={'common_valid_pixels':count,'common_spherical_area':area,
            'baseline_spherical_area':float(((base_mask>=128)*row_area).sum()),
            'candidate_spherical_area':float(((new_mask>=128)*row_area).sum()),
            'baseline_valid_pixels':int((base_mask>=128).sum()),'candidate_valid_pixels':int((new_mask>=128).sum()),
            'mask_changed_pixels':int(np.count_nonzero((base_mask>=128)!=(new_mask>=128)))}
    for label,render in [('baseline',baseline),('candidate',candidate)]:
        error=((reference.astype(np.float64)-render.astype(np.float64))/255.)**2
        pixel_error=error.mean(axis=2)
        result[label]={'spherical_squared_error_sum':float((pixel_error*weights).sum()),
                       'pixel_squared_error_sum':float(pixel_error[keep].sum())}
    return result


def pool(rows):
    area=sum(r['common_spherical_area'] for r in rows);count=sum(r['common_valid_pixels'] for r in rows)
    if area<=0 or count<=0:raise ValueError('No evaluation support')
    result={'frames':len(rows),'common_valid_pixels':count,'common_spherical_area':area}
    for label in ('baseline','candidate'):
        mse=sum(r[label]['spherical_squared_error_sum'] for r in rows)/area
        result[label]={'pooled_spherical_mse':mse,'pooled_spherical_psnr_db':-10*math.log10(mse) if mse else None,
                       'pooled_pixel_mse':sum(r[label]['pixel_squared_error_sum'] for r in rows)/count}
    before=result['baseline']['pooled_spherical_mse'];after=result['candidate']['pooled_spherical_mse']
    result['spherical_mse_ratio']=after/before if before else None
    pixel_before=result['baseline']['pooled_pixel_mse'];pixel_after=result['candidate']['pooled_pixel_mse']
    result['pixel_mse_ratio']=pixel_after/pixel_before if pixel_before else None
    result['spherical_error_halved']=before>0 and after<=before*.5
    result['pixel_error_halved']=pixel_before>0 and pixel_after<=pixel_before*.5
    result['baseline_support_retained']=area/sum(r['baseline_spherical_area'] for r in rows)
    result['minimum_frame_support_retained']=min(r['common_spherical_area']/r['baseline_spherical_area'] for r in rows)
    result['coverage_gate_passed']=result['baseline_support_retained']>=.99 and result['minimum_frame_support_retained']>=.9
    result['half_error_gate_passed']=result['spherical_error_halved'] and result['pixel_error_halved'] and result['coverage_gate_passed']
    result['psnr_gain_db']=10*math.log10(before/after) if before>0 and after>0 else None
    return result


def evaluate(base_manifest,base_run,new_manifest,new_run):
    old=json.loads(base_manifest.read_text());new=json.loads(new_manifest.read_text())
    order=old['heldout_evaluation_order']
    if not order or order!=new['heldout_evaluation_order'] or len(order)!=len(set(order)):
        raise ValueError('Evaluation camera identities or order differ')
    old_rows={r['name']:r for r in old['frames']};new_rows={r['name']:r for r in new['frames']}
    provenance={}
    signatures=[]
    for label,manifest,run in [('baseline',base_manifest,base_run),('candidate',new_manifest,new_run)]:
        config_path=run/'config.json';config=json.loads(config_path.read_text())
        if Path(config['data']).resolve()!=manifest.parent.resolve():raise ValueError(f'Render data path differs: {label}')
        camera=manifest.parent/'sparse/0/cameras.txt';poses=manifest.parent/'sparse/0/images.txt'
        signature=sorted(tuple(line.split()[1:]) for line in camera.read_text().splitlines() if line.strip() and not line.lstrip().startswith('#'))
        if not signature or any(row[0]!='EQUIRECTANGULAR' for row in signature):raise ValueError('Expected native ERP cameras')
        signatures.append(signature)
        provenance[label]={'camera_sha256':sha(camera),'poses_sha256':sha(poses),'config_sha256':sha(config_path),
                           'pose_semantics':'Each model renders its own estimated pose for the identical physical capture; different SfM gauges are allowed.'}
    if signatures[0]!=signatures[1]:raise ValueError('Evaluation projection or intrinsics differ')
    rows=[]
    for i,name in enumerate(order):
        a=old_rows[name];b=new_rows[name]
        for key in ('source_name','source_frame','lens','timestamp_microseconds','source_packet_pts'):
            if a[key]!=b[key]:raise ValueError(f'Reference identity differs: {name} {key}')
        source_a=base_manifest.parent/'images'/name;source_b=new_manifest.parent/'images'/name
        if sha(source_a)!=sha(source_b):raise ValueError(f'Source pixels differ: {name}')
        source=load(source_a)
        masks=[];predictions=[];hashes={}
        for label,manifest,run in [('baseline',base_manifest,base_run),('candidate',new_manifest,new_run)]:
            gt=load(run/f'eval-gt-{i:05d}.png')
            if gt.shape!=source.shape or np.max(np.abs(gt.astype(np.int16)-source.astype(np.int16)))>1:
                raise ValueError(f'Saved reference differs: {label} {name}')
            mask_path=run/f'eval-mask-{i:05d}.png';mask=load(mask_path,True)
            if not np.array_equal(mask,load(manifest.parent/'masks'/name,True)):
                raise ValueError(f'Saved validity differs: {label} {name}')
            pred_path=run/f'eval-render-{i:05d}.png';predictions.append(load(pred_path));masks.append(mask)
            hashes[label]={'render_sha256':sha(pred_path),'mask_sha256':sha(mask_path)}
        row=score(source,*predictions,*masks)
        row.update(name=name,source_frame=a['source_frame'],lens=a['lens'],source_sha256=sha(source_a),hashes=hashes)
        rows.append(row)
    return {'method':'Unaligned RGB error on identical source images and intersection of valid masks. Pool squared errors before PSNR; source positions used for SfM are not independent pose truth.',
            'mask_policy':'Mask changes are reported, and the same intersection scores both models. This numerical gate does not establish visible texture recovery.',
            'baseline_manifest_sha256':sha(base_manifest),'candidate_manifest_sha256':sha(new_manifest),
            'camera_provenance':provenance,'coverage_thresholds':{'pooled_retention':.99,'each_frame_retention':.9},
            'script_sha256':sha(Path(__file__)),'summary':pool(rows),'frames':rows}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('baseline_manifest','baseline_run','candidate_manifest','candidate_run','output'):p.add_argument(name,type=Path)
    a=p.parse_args();report=evaluate(a.baseline_manifest,a.baseline_run,a.candidate_manifest,a.candidate_run)
    with a.output.open('x') as f:json.dump(report,f,indent=2,allow_nan=False);f.write('\n')
    print(json.dumps(report['summary'],indent=2))
if __name__=='__main__':main()
