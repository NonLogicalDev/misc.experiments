#!/usr/bin/env python3
"""Select synchronized sharp-frame candidates using temporary physical-lens ERP exports."""
import argparse
import bisect
import csv
from decimal import Decimal
from fractions import Fraction
import json
import os
import signal
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

import cv2
import numpy as np
from scipy.spatial.transform import Rotation
import prepare_dense_rig as dense
import prepare_rig as rig

MAX_BYTES = 40 * 1024**2
REPORT_BYTES = 5 * 1024**2


def windows(targets, radius, available):
    if not targets or targets != sorted(set(targets)) or min(targets) < 0 or not 0 <= radius <= 15:
        raise ValueError('Targets must be nonnegative, unique and sorted; use radius 0..15')
    candidates = []
    for i, target in enumerate(targets):
        lo, hi = target-radius, target+radius
        if i: lo = max(lo, (targets[i-1]+target)//2+1)
        if i+1 < len(targets): hi = min(hi, (target+targets[i+1])//2)
        group = [n for n in range(lo, hi+1) if n in available]
        if target not in group: raise ValueError(f'Missing target or orientation: {target}')
        candidates.append(group)
    return candidates


def pair_pts(micros, streams, packets):
    pair = dense.matched_pts(micros, streams, packets)
    times = [Fraction(item['pts'])*Fraction(item['time_base']) for item in pair]
    if len(pair) != 2 or times[0] != times[1]:
        raise ValueError('Missing or unsynchronized physical lens pair')
    return pair


def tile_energies(image, valid):
    if image.shape != valid.shape or image.ndim != 2:
        raise ValueError('Image and mask shape mismatch')
    gray = cv2.GaussianBlur(image.astype(np.float32), (0, 0), 1.0)
    size=(image.shape[1]//2, image.shape[0]//2)
    gray=cv2.resize(gray,size,interpolation=cv2.INTER_AREA)
    valid=cv2.resize(valid.astype(np.float32),size,interpolation=cv2.INTER_AREA) >= 1.0
    valid=cv2.erode(valid.astype(np.uint8),np.ones((7,7),np.uint8),borderType=cv2.BORDER_CONSTANT,borderValue=0)>0
    gx=cv2.Sobel(gray,cv2.CV_32F,1,0,ksize=3)/8
    gy=cv2.Sobel(gray,cv2.CV_32F,0,1,ksize=3)/8
    energy=np.clip(np.maximum(gx*gx+gy*gy-4,0),0,400)
    return energy,valid


def score_window(images, masks, target_index):
    """Use common pixels and tiles textured in any candidate for all candidates."""
    prepared=[tile_energies(im,mask) for im,mask in zip(images,masks)]
    common=np.logical_and.reduce([valid for _,valid in prepared])
    tiles=[]
    h,w=common.shape
    for y in range(0,h,32):
        for x in range(0,w,32):
            m=common[y:y+32,x:x+32]
            if m.shape != (32,32) or m.mean()<.7: continue
            texture=max(float(np.mean(energy[y:y+32,x:x+32][m])) for energy,_ in prepared)
            if texture>=12: tiles.append((y,x,m))
    if len(tiles)<4: raise ValueError('Insufficient valid textured tiles')
    return [{'score':float(np.median([np.mean(energy[y:y+32,x:x+32][m]) for y,x,m in tiles])),
             'textured_tiles':len(tiles),'valid_pixels':int(common.sum())} for energy,_ in prepared]


def select(target, candidates):
    if not candidates: raise ValueError('No valid paired candidates')
    return max(candidates, key=lambda x: (min(x['lenses'][0]['score'], x['lenses'][1]['score']), -abs(x['frame']-target), -x['frame']))


def run(source, review_path, fused_path, output, targets, radius, timeout):
    source, review_path, fused_path = [Path(p).resolve(strict=True) for p in (source, review_path, fused_path)]
    output = Path(output).resolve()
    if output.exists(): raise FileExistsError(output)
    if not np.isfinite(timeout) or timeout <= 0: raise ValueError('Timeout must be positive')
    review = json.loads(review_path.read_text())
    if review['frame_dimensions'] != [1024, 512]: raise ValueError('Expected reviewed 1024x512 stable masks')
    reviewed = sorted(review['frames'], key=lambda x:x['source_frame'])
    keys = [r['source_frame'] for r in reviewed]
    if keys != sorted(set(keys)): raise ValueError('Duplicate reviewed frames')
    with fused_path.open(newline='') as f: rows = list(csv.DictReader(f))
    fused = {int(row['frame']):row for row in rows}
    if len(fused) != len(rows): raise ValueError('Duplicate fused frame')
    groups = windows(targets, radius, fused)
    streams, packets = dense.packet_map(source)
    exporter = Path(__file__).with_name('export_timestamp_probes.py')
    mask_cache = {}
    mask_hashes = {}
    def mask(item):
        path = (review_path.parent/'masks'/item['mask']).resolve(strict=True)
        if path not in mask_cache:
            arr = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
            if arr is None or arr.shape != (512,1024) or not np.isin(arr, [0,255]).all(): raise ValueError(f'Invalid reviewed mask: {path}')
            mask_cache[path] = arr == 255; mask_hashes[str(path)] = rig.sha(path)
        return mask_cache[path]
    output.mkdir(); (output/'INCOMPLETE').write_text('Selection not complete\n')
    results=[]; evidence=[]
    def check():
        size=sum(p.stat().st_size for p in output.rglob('*') if p.is_file())
        if size > MAX_BYTES or shutil.disk_usage(output).free < 35*1024**3:
            raise RuntimeError('40 MiB output cap or 35 GiB free-space reserve exceeded')
    check()
    for target, group in zip(targets, groups):
        candidates=[]
        for start in range(0,len(group),8):
            batch=group[start:start+8]; times=[]; metadata=[]
            for n in batch:
                row=fused[n]; t=Decimal(row['video_pts_s']); us=t*1000000
                if not t.is_finite() or us != int(us): raise ValueError(f'Invalid exact timestamp for {n}')
                us=int(us); pair=pair_pts(us, streams, packets)
                i=bisect.bisect_left(keys,n)
                if i<len(keys) and keys[i]==n: before=after=reviewed[i]
                elif i==0 or i==len(keys): raise ValueError(f'No bracketing reviewed masks: {n}')
                else: before,after=reviewed[i-1],reviewed[i]
                for item in (before,after):
                    if item['source_frame'] not in fused or abs(float(fused[item['source_frame']]['video_pts_s'])-float(item['video_pts_s']))>1e-5: raise ValueError('Reviewed mask timestamp mismatch')
                stable=mask(before)&mask(after)
                q=Rotation.from_quat([float(row[k]) for k in ('q_x','q_y','q_z','q_w')]).as_matrix()
                transform=q.T@Rotation.from_euler('z',float(row['heading_rad'])).as_matrix()
                keep=rig.operator_body_keep(stable,transform)
                times.append(str(t));metadata.append((n,us,pair,before,after,keep))
            with tempfile.TemporaryDirectory(prefix='.batch-',dir=output) as tmp:
                dest=Path(tmp)/'export'; log=Path(tmp)/'export.log'
                cmd=[sys.executable,str(exporter),'--source',str(source),'--output',str(dest),'--indices',*map(str,batch),'--timestamps',*times,'--width','1024','--seek-early-us','1']
                with log.open('wb') as out:
                    proc=subprocess.Popen(cmd,stdout=out,stderr=subprocess.STDOUT,start_new_session=True)
                    started=time.monotonic()
                    try:
                        while proc.poll() is None:
                            if time.monotonic()-started>timeout: raise TimeoutError('Candidate export timed out')
                            check();time.sleep(.25)
                        if proc.returncode:
                            failure=log.read_bytes()[-16384:]; (output/'failure.log').write_bytes(failure)
                            raise RuntimeError(f'Candidate exporter failed: {failure[-2000:].decode(errors="replace")}')
                    except BaseException:
                        out.flush()
                        (output/'failure.log').write_bytes(log.read_bytes()[-16384:])
                        raise
                    finally:
                        if proc.poll() is None: os.killpg(proc.pid,signal.SIGKILL);proc.wait()
                check(); data=json.loads((dest/'manifest.json').read_text())
                if len(data['frames'])!=len(batch): raise ValueError('Missing physical lens pair')
                for frame,(n,us,pair,before,after,keep) in zip(data['frames'],metadata):
                    if frame['frame']!=n or frame['timestamp_microseconds']!=us: raise ValueError('Export frame/PTS mismatch')
                    images=[]; masks=[]
                    for lens in range(2):
                        img=cv2.imread(frame[f'lens{lens}'],cv2.IMREAD_COLOR);support=cv2.imread(frame[f'mask{lens}'],cv2.IMREAD_GRAYSCALE)
                        if img is None or support is None or img.shape!=(512,1024,3) or support.shape!=(512,1024): raise ValueError('Missing physical lens pair')
                        images.append(img);masks.append(keep & (support==255))
                    candidates.append({'frame':n,'timestamp_microseconds':us,'source_packet_pts':pair,'mask_brackets':[before['source_frame'],after['source_frame']],'export_sha256':{k:frame[k+'_sha256'] for k in ('lens0','lens1','mask0','mask1')},'_images':images,'_masks':masks,'lenses':[]})
            check()
        target_index=group.index(target)
        for lens in range(2):
            scores=score_window([cv2.cvtColor(c['_images'][lens],cv2.COLOR_BGR2GRAY) for c in candidates],[c['_masks'][lens] for c in candidates],target_index)
            for candidate,score in zip(candidates,scores): candidate['lenses'].append(score)
        winner=select(target,candidates)
        if len(evidence)<4:
            requested=candidates[target_index]
            rows=[]
            for lens in range(2):
                images=[cv2.resize(c['_images'][lens],(512,256),interpolation=cv2.INTER_AREA) for c in (requested,winner)]
                heading=np.zeros((24,1024,3),np.uint8)
                cv2.putText(heading,f'cam{lens} requested {target}',(5,17),cv2.FONT_HERSHEY_SIMPLEX,.45,(255,255,255),1,cv2.LINE_AA)
                cv2.putText(heading,f'cam{lens} selected {winner["frame"]}',(517,17),cv2.FONT_HERSHEY_SIMPLEX,.45,(255,255,255),1,cv2.LINE_AA)
                rows.append(np.vstack((heading,np.hstack(images))))
            evidence.append(np.vstack(rows))
        for candidate in candidates: del candidate['_images']; del candidate['_masks']
        results.append({'requested_frame':target,'requested_timestamp_microseconds':int(Decimal(fused[target]['video_pts_s'])*1000000),'selected_frame':winner['frame'],'selected_timestamp_microseconds':winner['timestamp_microseconds'],'candidates':candidates})
    native=importlib.util.find_spec('insta360_rs._native')
    if native is None or not native.origin: raise ValueError('Cannot identify native exporter extension')
    report={'native_extension':native.origin,'native_extension_sha256':rig.sha(Path(native.origin)), 'method':'Paired timestamp ERP exports; intersection of bracketing reviewed stable masks rotated by candidate fused orientation; source support and eroded score boundary. Median pooled-texture common tile smoothed gradient energy, noise floor and capped edge contribution; pair score is weaker lens. Propagated masks are approximate; camera motion changes the scene at a pixel and scores do not guarantee motion or noise removal. Frame indices are fused CSV labels; packet matching validates timestamps, not independent frame-index identity. Winners require actual-frame reviewed masks and fresh SfM; no old poses may be reused.', 'source':str(source),'source_sha256':rig.sha(source),'review_manifest':str(review_path),'review_manifest_sha256':rig.sha(review_path),'fused_csv':str(fused_path),'fused_csv_sha256':rig.sha(fused_path),'exporter_sha256':rig.sha(exporter),'selector_sha256':rig.sha(Path(__file__)),'review_mask_sha256':mask_hashes,'selected_indices':[x['selected_frame'] for x in results],'selected_timestamps_microseconds':[x['selected_timestamp_microseconds'] for x in results],'radius':radius,'score_config':{'export_width':1024,'score_width':512,'gaussian_sigma':1.0,'downsample':'area 2x','mask_resize':'float area all-valid','erosion_size':7,'tile_size':32,'tile_valid_fraction':0.7,'gradient':'3x3 Sobel divided by 8','energy_noise_floor':4.0,'energy_cap':400.0,'pooled_texture_mean_min':12.0,'minimum_tiles':4,'aggregate':'median pooled-textured common tiles, minimum of two lens scores','batch_size':8,'seek_early_us':1,'evidence_first_targets':4,'evidence_size_per_image':[512,256],'max_output_bytes':MAX_BYTES,'minimum_free_bytes':35*1024**3},'results':results}
    raw=(json.dumps(report,indent=2,allow_nan=False)+'\n').encode()
    if len(raw)>REPORT_BYTES: raise RuntimeError('Report exceeds 5 MiB')
    (output/'selection.json').write_bytes(raw)
    if evidence and not cv2.imwrite(str(output/'evidence.png'),np.vstack(evidence),[cv2.IMWRITE_PNG_COMPRESSION,6]): raise OSError('Cannot write evidence')
    check()
    if sum(p.stat().st_size for p in output.iterdir() if p.is_file()) > REPORT_BYTES: raise RuntimeError('Final evidence exceeds 5 MiB')
    (output/'INCOMPLETE').unlink()
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path);p.add_argument('review_manifest',type=Path);p.add_argument('fused_csv',type=Path);p.add_argument('output',type=Path)
    p.add_argument('--targets',type=int,nargs='+',required=True);p.add_argument('--radius',type=int,default=2);p.add_argument('--timeout',type=float,default=300)
    a=p.parse_args();run(a.source,a.review_manifest,a.fused_csv,a.output,a.targets,a.radius,a.timeout)


if __name__=='__main__': main()
