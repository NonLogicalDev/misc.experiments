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
    return set(low)



def validate_pose_pair(low_text, high_text, low_frames, high_frames, order, allow_estimated_pose_change=False):
    """Validate every compared capture's camera assignment, including in strict mode."""
    def parse(text, frames):
        expected={}
        for row in frames:
            name=row['name']
            if name in expected:raise ValueError(f'Duplicate manifest image: {name}')
            expected[name]=str(row['colmap_camera_id'])
        lines=text.splitlines();found={};i=0
        while i<len(lines):
            line=lines[i].strip();i+=1
            if not line or line.startswith('#'):continue
            fields=line.split()
            if len(fields)!=10:raise ValueError('Invalid COLMAP pose row')
            name=fields[9]
            if name in found:raise ValueError(f'Duplicate pose image: {name}')
            try:q=np.array([float(v) for v in fields[1:5]]);t=np.array([float(v) for v in fields[5:8]])
            except ValueError as exc:raise ValueError(f'Invalid pose values: {name}') from exc
            if not np.isfinite(q).all() or not np.isfinite(t).all() or not np.isclose(np.linalg.norm(q),1,rtol=0,atol=1e-5):raise ValueError(f'Invalid pose values: {name}')
            found[name]=fields[8]
            if i>=len(lines):raise ValueError(f'Missing COLMAP point row: {name}')
            i+=1
        for name in order:
            if name not in expected or name not in found:raise ValueError(f'Missing compared image: {name}')
            if found[name]!=expected[name]:raise ValueError(f'Wrong camera ID: {name}')
        return expected
    low_expected=parse(low_text,low_frames);high_expected=parse(high_text,high_frames)
    if any(low_expected[name]!=high_expected[name] for name in order):raise ValueError('Compared camera IDs differ')
    if not allow_estimated_pose_change and low_text!=high_text:raise ValueError('Camera poses differ across resolutions')



def validate_capture_identity(low,high,name):
    for key in ('source_name','source_frame','lens','timestamp_microseconds','source_packet_pts'):
        if low[key]!=high[key]:raise ValueError(f'Capture identity mismatch: {name} {key}')


def reduce_candidate(high_reference,high_mask,low_reference,low_mask,high_render):
    if high_reference.shape!=(1024,2048,3) or high_render.shape!=high_reference.shape or high_mask.shape!=(1024,2048) or low_reference.shape!=(512,1024,3) or low_mask.shape!=(512,1024):raise ValueError('Unexpected ERP image dimensions')
    support=(high_mask>=128).reshape(512,2,1024,2).all(axis=(1,3));expected=low_mask>=128
    if not np.array_equal(support,expected):raise ValueError('Reduced support differs from fixed 1024 mask')
    reduced=cv2.resize(high_reference,(1024,512),interpolation=cv2.INTER_AREA)
    if not np.array_equal(reduced[expected],low_reference[expected]):raise ValueError('Reduced source differs from fixed 1024 reference on valid pixels')
    return cv2.resize(high_render,(1024,512),interpolation=cv2.INTER_AREA)


def evaluate(low_manifest,low_run,high_manifest,high_run,allow_estimated_pose_change=False):
    low_manifest,low_run,high_manifest,high_run=(Path(x).resolve(strict=True) for x in (low_manifest,low_run,high_manifest,high_run));lo=json.loads(low_manifest.read_text());hi=json.loads(high_manifest.read_text());order=lo['heldout_evaluation_order']
    if len(order)!=36 or order!=hi['heldout_evaluation_order'] or len(set(order))!=len(order):raise ValueError('Heldout order mismatch')
    lowcamera=low_manifest.parent/'sparse/0/cameras.txt';highcamera=high_manifest.parent/'sparse/0/cameras.txt';camera_ids=validate_cameras(lowcamera.read_text(),highcamera.read_text())
    if any(str(r['colmap_camera_id']) not in camera_ids for m in (lo,hi) for r in m['frames'] if r['name'] in order):raise ValueError('Compared image references unknown camera ID')
    lowposes=low_manifest.parent/'sparse/0/images.txt';highposes=high_manifest.parent/'sparse/0/images.txt'
    validate_pose_pair(lowposes.read_text(),highposes.read_text(),lo['frames'],hi['frames'],order,allow_estimated_pose_change)
    if not allow_estimated_pose_change and lowposes.read_bytes()!=highposes.read_bytes():raise ValueError('Camera poses differ across resolutions')
    transforms=[]
    for label,manifest,run in (('baseline',low_manifest,low_run),('candidate',high_manifest,high_run)):
        config=json.loads((run/'config.json').read_text())
        if Path(config['data']).resolve()!=manifest.parent:raise ValueError(f'Render data path differs: {label}')
        if config.get('eval_align') is not False:raise ValueError(f'Evaluation alignment must be explicitly disabled: {label}')
        path=run/'scene_transform.json';transform=json.loads(path.read_text());transforms.append(transform['train_from_world']['matrix_4x4'])
    if transforms[0]!=transforms[1]:raise ValueError('Scene transforms differ across resolutions')
    lr={x['name']:x for x in lo['frames']};hr={x['name']:x for x in hi['frames']};rows=[]
    for i,name in enumerate(order):
        validate_capture_identity(lr[name],hr[name],name)
        lowref=pixels.load(low_manifest.parent/'images'/name);highref=pixels.load(high_manifest.parent/'images'/name);lowmask=pixels.load(low_manifest.parent/'masks'/name,True);highmask=pixels.load(high_manifest.parent/'masks'/name,True)
        oldgt=pixels.load(low_run/f'eval-gt-{i:05d}.png');newgt=pixels.load(high_run/f'eval-gt-{i:05d}.png');oldmask=pixels.load(low_run/f'eval-mask-{i:05d}.png',True);newmask=pixels.load(high_run/f'eval-mask-{i:05d}.png',True)
        if np.max(np.abs(oldgt.astype(np.int16)-lowref.astype(np.int16)))>1 or np.max(np.abs(newgt.astype(np.int16)-highref.astype(np.int16)))>1:raise ValueError(f'Saved reference differs: {name}')
        if not np.array_equal(oldmask,lowmask) or not np.array_equal(newmask,highmask):raise ValueError(f'Saved support differs: {name}')
        baseline=pixels.load(low_run/f'eval-render-{i:05d}.png');newrender=pixels.load(high_run/f'eval-render-{i:05d}.png');candidate=reduce_candidate(highref,highmask,lowref,lowmask,newrender)
        row=pixels.score(lowref,baseline,candidate,lowmask,lowmask);row.update(name=name,source_frame=lr[name]['source_frame'],lens=lr[name]['lens'],low_reference_sha256=pixels.sha(low_manifest.parent/'images'/name),high_reference_sha256=pixels.sha(high_manifest.parent/'images'/name),low_mask_sha256=pixels.sha(low_manifest.parent/'masks'/name),high_mask_sha256=pixels.sha(high_manifest.parent/'masks'/name),baseline_render_sha256=pixels.sha(low_run/f'eval-render-{i:05d}.png'),candidate_render_sha256=pixels.sha(high_run/f'eval-render-{i:05d}.png'));rows.append(row)
    return {'comparison_mode':('estimated poses: end-to-end reconstructions at corresponding observed captures; pose and reconstruction changes are combined' if allow_estimated_pose_change else 'identical pose files: fixed-pose comparison'),'method':'Candidate render area-reduced 2x to fixed 1024 captures. Each 2x2 high-resolution support block must exactly reproduce the low-resolution mask, and high-reference area reduction must exactly reproduce low-reference RGB on valid pixels. No alignment.','low_manifest_sha256':pixels.sha(low_manifest),'high_manifest_sha256':pixels.sha(high_manifest),'script_sha256':pixels.sha(Path(__file__)),'low_camera_sha256':pixels.sha(lowcamera),'high_camera_sha256':pixels.sha(highcamera),'baseline_config_sha256':pixels.sha(low_run/'config.json'),'candidate_config_sha256':pixels.sha(high_run/'config.json'),'pose_sha256':pixels.sha(lowposes),'baseline_pose_sha256':pixels.sha(lowposes),'candidate_pose_sha256':pixels.sha(highposes),'baseline_scene_transform_sha256':pixels.sha(low_run/'scene_transform.json'),'candidate_scene_transform_sha256':pixels.sha(high_run/'scene_transform.json'),'saved_reference_tolerance':'At most one RGB level versus each prepared reference; scoring uses the prepared 1024 source.', 'summary':pixels.pool(rows),'frames':rows}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('low_manifest','low_run','high_manifest','high_run','output'):p.add_argument(name,type=Path)
    p.add_argument('--allow-estimated-pose-change',action='store_true',help='Compare end-to-end reconstructions using corresponding captures with different estimated poses')
    a=p.parse_args();report=evaluate(a.low_manifest,a.low_run,a.high_manifest,a.high_run,a.allow_estimated_pose_change)
    with a.output.open('x') as f:json.dump(report,f,indent=2,allow_nan=False);f.write('\n')
    print(json.dumps(report['summary'],indent=2))
if __name__=='__main__':main()
