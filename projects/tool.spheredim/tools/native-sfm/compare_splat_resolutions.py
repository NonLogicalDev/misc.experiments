#!/usr/bin/env python3
"""Compare native 1024 renders to area-reduced native 2048 renders on fixed captures."""
import argparse, json
from pathlib import Path
import cv2
import numpy as np
import compare_splat_pixels as pixels


def validate_cameras(low_text,high_text):
    def parse(text,width,height):
        result={}
        for line in text.splitlines():
            if not line.strip() or line.lstrip().startswith('#'):continue
            row=line.split()
            if len(row)!=6 or row[1]!='EQUIRECTANGULAR' or int(row[2])!=width or int(row[3])!=height or row[0] in result:raise ValueError('Unexpected ERP camera model or dimensions')
            result[row[0]]=(float(row[4]),float(row[5]))
        if not result:raise ValueError('Missing ERP cameras')
        return result
    low=parse(low_text,1024,512);high=parse(high_text,2048,1024)
    if set(low)!=set(high) or any(not np.allclose(np.array(high[k]),2*np.array(low[k]),rtol=0,atol=1e-9) for k in low):raise ValueError('ERP camera intrinsics differ')


def reduce_candidate(high_reference,high_mask,low_reference,low_mask,high_render):
    if high_reference.shape!=(1024,2048,3) or high_render.shape!=high_reference.shape or high_mask.shape!=(1024,2048) or low_reference.shape!=(512,1024,3) or low_mask.shape!=(512,1024):raise ValueError('Unexpected ERP image dimensions')
    support=(high_mask>=128).reshape(512,2,1024,2).all(axis=(1,3));expected=low_mask>=128
    if not np.array_equal(support,expected):raise ValueError('Reduced support differs from fixed 1024 mask')
    reduced=cv2.resize(high_reference,(1024,512),interpolation=cv2.INTER_AREA)
    if not np.array_equal(reduced[expected],low_reference[expected]):raise ValueError('Reduced source differs from fixed 1024 reference on valid pixels')
    return cv2.resize(high_render,(1024,512),interpolation=cv2.INTER_AREA)


def evaluate(low_manifest,low_run,high_manifest,high_run):
    low_manifest,low_run,high_manifest,high_run=(Path(x).resolve(strict=True) for x in (low_manifest,low_run,high_manifest,high_run));lo=json.loads(low_manifest.read_text());hi=json.loads(high_manifest.read_text());order=lo['heldout_evaluation_order']
    if len(order)!=36 or order!=hi['heldout_evaluation_order'] or len(set(order))!=len(order):raise ValueError('Heldout order mismatch')
    lowcamera=low_manifest.parent/'sparse/0/cameras.txt';highcamera=high_manifest.parent/'sparse/0/cameras.txt';validate_cameras(lowcamera.read_text(),highcamera.read_text())
    lowposes=low_manifest.parent/'sparse/0/images.txt';highposes=high_manifest.parent/'sparse/0/images.txt'
    if lowposes.read_bytes()!=highposes.read_bytes():raise ValueError('Camera poses differ across resolutions')
    transforms=[]
    for label,manifest,run in (('baseline',low_manifest,low_run),('candidate',high_manifest,high_run)):
        config=json.loads((run/'config.json').read_text())
        if Path(config['data']).resolve()!=manifest.parent:raise ValueError(f'Render data path differs: {label}')
        path=run/'scene_transform.json';transform=json.loads(path.read_text());transforms.append(transform['train_from_world']['matrix_4x4'])
    if transforms[0]!=transforms[1]:raise ValueError('Scene transforms differ across resolutions')
    lr={x['name']:x for x in lo['frames']};hr={x['name']:x for x in hi['frames']};rows=[]
    for i,name in enumerate(order):
        for key in ('source_name','source_frame','lens','timestamp_microseconds','source_packet_pts'):
            if lr[name][key]!=hr[name][key]:raise ValueError(f'Capture identity mismatch: {name} {key}')
        lowref=pixels.load(low_manifest.parent/'images'/name);highref=pixels.load(high_manifest.parent/'images'/name);lowmask=pixels.load(low_manifest.parent/'masks'/name,True);highmask=pixels.load(high_manifest.parent/'masks'/name,True)
        oldgt=pixels.load(low_run/f'eval-gt-{i:05d}.png');newgt=pixels.load(high_run/f'eval-gt-{i:05d}.png');oldmask=pixels.load(low_run/f'eval-mask-{i:05d}.png',True);newmask=pixels.load(high_run/f'eval-mask-{i:05d}.png',True)
        if np.max(np.abs(oldgt.astype(np.int16)-lowref.astype(np.int16)))>1 or np.max(np.abs(newgt.astype(np.int16)-highref.astype(np.int16)))>1:raise ValueError(f'Saved reference differs: {name}')
        if not np.array_equal(oldmask,lowmask) or not np.array_equal(newmask,highmask):raise ValueError(f'Saved support differs: {name}')
        baseline=pixels.load(low_run/f'eval-render-{i:05d}.png');newrender=pixels.load(high_run/f'eval-render-{i:05d}.png');candidate=reduce_candidate(highref,highmask,lowref,lowmask,newrender)
        row=pixels.score(lowref,baseline,candidate,lowmask,lowmask);row.update(name=name,source_frame=lr[name]['source_frame'],lens=lr[name]['lens'],low_reference_sha256=pixels.sha(low_manifest.parent/'images'/name),high_reference_sha256=pixels.sha(high_manifest.parent/'images'/name),low_mask_sha256=pixels.sha(low_manifest.parent/'masks'/name),high_mask_sha256=pixels.sha(high_manifest.parent/'masks'/name),baseline_render_sha256=pixels.sha(low_run/f'eval-render-{i:05d}.png'),candidate_render_sha256=pixels.sha(high_run/f'eval-render-{i:05d}.png'));rows.append(row)
    return {'method':'Candidate render area-reduced 2x to fixed 1024 captures. Each 2x2 high-resolution support block must exactly reproduce the low-resolution mask, and high-reference area reduction must exactly reproduce low-reference RGB on valid pixels. No alignment.','low_manifest_sha256':pixels.sha(low_manifest),'high_manifest_sha256':pixels.sha(high_manifest),'script_sha256':pixels.sha(Path(__file__)),'low_camera_sha256':pixels.sha(lowcamera),'high_camera_sha256':pixels.sha(highcamera),'baseline_config_sha256':pixels.sha(low_run/'config.json'),'candidate_config_sha256':pixels.sha(high_run/'config.json'),'pose_sha256':pixels.sha(lowposes),'baseline_scene_transform_sha256':pixels.sha(low_run/'scene_transform.json'),'candidate_scene_transform_sha256':pixels.sha(high_run/'scene_transform.json'),'saved_reference_tolerance':'At most one RGB level versus each prepared reference; scoring uses the prepared 1024 source.', 'summary':pixels.pool(rows),'frames':rows}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('low_manifest','low_run','high_manifest','high_run','output'):p.add_argument(name,type=Path)
    a=p.parse_args();report=evaluate(a.low_manifest,a.low_run,a.high_manifest,a.high_run)
    with a.output.open('x') as f:json.dump(report,f,indent=2,allow_nan=False);f.write('\n')
    print(json.dumps(report['summary'],indent=2))
if __name__=='__main__':main()
