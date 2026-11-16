#!/usr/bin/env python3
"""Stream full-ERP frames and propagate reviewed raw keys into unreviewed candidates."""
import argparse
import csv
import hashlib
import json
import os
import select
from pathlib import Path
import shutil
import signal
import subprocess
import time

import cv2
import numpy as np
from scipy.spatial.transform import Rotation
from propagate_candidates import flow, remap, consistent
from warp_sequence import spherical_guard, warp

RESERVE = 35 * 1024**3
BUDGET = 180 * 1024**2
WIDTH, HEIGHT = 1024, 512


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()


def check_storage(root):
    used=sum(p.stat().st_size for p in root.rglob('*') if p.is_file())
    if used>BUDGET or shutil.disk_usage(root).free<RESERVE:
        raise RuntimeError('Output budget or free-space reserve exceeded')


def stream(video, first, last, stride, count):
    return subprocess.Popen(['ffmpeg','-hide_banner','-loglevel','error','-i',str(video),'-vf',f'select=gte(n\\,{first})*lte(n\\,{last})*not(mod(n-{first}\\,{stride})),scale=1024:512','-fps_mode','passthrough','-frames:v',str(count),'-f','rawvideo','-pix_fmt','bgr24','pipe:1'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,start_new_session=True)


def read_frame(proc, root):
    needed=WIDTH*HEIGHT*3; chunks=[]; deadline=time.monotonic()+120
    while needed:
        ready,_,_=select.select([proc.stdout],[],[],1)
        check_storage(root)
        if not ready:
            if time.monotonic()>deadline: raise TimeoutError('Frame decoder timed out')
            continue
        part=os.read(proc.stdout.fileno(),needed)
        if not part: raise RuntimeError('Short frame stream')
        chunks.append(part);needed-=len(part)
    return np.frombuffer(b''.join(chunks),np.uint8).reshape(HEIGHT,WIDTH,3).copy()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('off_video','stable_video','fused_csv','raw_keys','review_manifest','output'):p.add_argument(name,type=Path)
    p.add_argument('--sample-stride',type=int,default=5)
    a=p.parse_args(); root=a.output;root.mkdir(parents=True,exist_ok=False);(root/'INCOMPLETE').write_text('Candidate generation incomplete\n')
    for d in ('camera-relative','stabilized','review'): (root/d).mkdir()
    check_storage(root)
    with a.fused_csv.open(newline='') as f:rows=list(csv.DictReader(f))
    reviewed=json.loads(a.review_manifest.read_text()); keys={x['source_frame']:x for x in reviewed['frames']}
    ordered=sorted(keys)
    if len(ordered)<2 or len(ordered)!=len(reviewed['frames']) or a.sample_stride<=0:
        raise ValueError('Expected at least two unique reviewed keys and a positive sample stride')
    cadence=ordered[1]-ordered[0]
    if cadence<=0 or any(b-a!=cadence for a,b in zip(ordered,ordered[1:])) or cadence%a.sample_stride:
        raise ValueError('Keys must have uniform cadence divisible by sample stride')
    first,last=ordered[0],ordered[-1];group=cadence//a.sample_stride
    count=(last-first)//a.sample_stride+1
    raw_ordinal={n:i for i,n in enumerate(ordered)}
    for video in (a.off_video,a.stable_video):
        info=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-show_entries','frame=best_effort_timestamp_time','-of','json',str(video)],timeout=300))['frames']
        for n in range(first,last+1,a.sample_stride):
            if n>=len(info) or int(rows[n]['frame'])!=n or abs(float(info[n]['best_effort_timestamp_time'])-float(rows[n]['video_pts_s']))>1e-5:raise ValueError(f'PTS mismatch at {video} frame {n}')
    source_hashes={str(x.resolve()):digest(x) for x in (a.off_video,a.stable_video,a.fused_csv,a.review_manifest)}
    streams=[stream(a.off_video,first,last,a.sample_stride,count),stream(a.stable_video,first,last,a.sample_stride,count)];started=time.monotonic();records=[];cells=[];sheets=[]
    def source(): return (read_frame(streams[0],root),read_frame(streams[1],root))
    def save(ordinal,src,exclude,key):
        n=first+ordinal*a.sample_stride; row=rows[n]
        q=[float(row[k]) for k in ('q_x','q_y','q_z','q_w')]
        rotation=Rotation.from_quat(q).as_matrix().T @ Rotation.from_euler('z',float(row['heading_rad'])).as_matrix()
        keep=255-spherical_guard(warp(spherical_guard(exclude,4),rotation),32)
        name=f'frame_{n:06d}.png';raw=255-exclude
        for folder,image in (('camera-relative',raw),('stabilized',keep)):
            if not cv2.imwrite(str(root/folder/name),image):raise OSError(name)
        if key and digest(root/'stabilized'/name)!=digest(a.review_manifest.parent/'masks'/keys[n]['mask']):
            raise ValueError(f'Key mask differs from reviewed source at {n}')
        overlay=src[1].copy();overlay[keep==0]=(overlay[keep==0]*.35+np.array([0,0,165])).clip(0,255)
        thumb=cv2.resize(overlay,(512,256),interpolation=cv2.INTER_AREA);cv2.rectangle(thumb,(0,0),(512,24),(0,0,0),-1)
        cv2.putText(thumb,f'UNREVIEWED frame {n} {float(row["video_pts_s"]):.3f}s',(5,17),cv2.FONT_HERSHEY_SIMPLEX,.45,(255,255,255),1,cv2.LINE_AA)
        cells.append(thumb)
        records.append({'source_frame':n,'video_pts_s':float(row['video_pts_s']),'keyframe':key,'off_rgb_sha256':hashlib.sha256(src[0].tobytes()).hexdigest(),'stable_rgb_sha256':hashlib.sha256(src[1].tobytes()).hexdigest(),'candidate_sha256':digest(root/'camera-relative'/name),'stabilized_sha256':digest(root/'stabilized'/name),'mask':name})
        if len(cells)==8 or ordinal==count-1:
            group=cells[:];group += [np.zeros_like(cells[0])]*(8-len(group))
            sheet=np.vstack([np.hstack(group[i:i+2]) for i in range(0,8,2)]);sheet_name=f'review-{len(sheets):03d}.jpg'
            if not cv2.imwrite(str(root/'review'/sheet_name),sheet):raise OSError(sheet_name)
            sheets.append({'name':sheet_name,'sha256':digest(root/'review'/sheet_name)});cells.clear()
        check_storage(root)
    try:
        previous=source()
        for start in range(0,count-1,group):
            chunk=[previous]+[source() for _ in range(group)]
            left_n=first+start*a.sample_stride;right_n=left_n+cadence
            def key(n):
                path=a.raw_keys/f'frame_{raw_ordinal[n]:05d}.png';img=cv2.imread(str(path),cv2.IMREAD_GRAYSCALE)
                if img is None or img.shape!=(HEIGHT,WIDTH):raise ValueError(f'Invalid key {n}')
                return np.where(img<128,255,0).astype(np.uint8)
            left,right=key(left_n),key(right_n)
            grayscale=[cv2.cvtColor(x[0],cv2.COLOR_BGR2GRAY) for x in chunk]
            prev,next_={},{}
            for i in range(group):prev[i+1]=flow(grayscale[i],grayscale[i+1]);next_[i]=flow(grayscale[i+1],grayscale[i])
            lefts={};rights={};ll={};lr={}
            for i in range(1,group):left=remap(left,prev[i]);lefts[i]=left.copy();ll[i]=~consistent(prev[i],next_[i-1])
            for i in range(group-1,0,-1):right=remap(right,next_[i]);rights[i]=right.copy();lr[i]=~consistent(next_[i],prev[i+1])
            if start==0:save(0,chunk[0],key(left_n),True)
            for i in range(1,group):
                union=cv2.bitwise_or(lefts[i],rights[i]);near=spherical_guard(union,2)
                uncertain=(ll[i]|lr[i]|(lefts[i]!=rights[i]))&(near>0)
                exclude=cv2.bitwise_or(near,spherical_guard(np.where(uncertain,255,0).astype(np.uint8),2))
                save(start+i,chunk[i],exclude,False)
            save(start+group,chunk[group],key(right_n),True);previous=chunk[group]
        for proc in streams:
            if proc.wait(timeout=30)!=0: raise RuntimeError('Frame decoder failed')
        result={'status':'UNREVIEWED candidates; visual inspection and explicit approval required', 'source_hashes':source_hashes,'reviewed_key_count':len(ordered),'sample_stride':a.sample_stride,'key_stride':cadence,'frame_count':len(records),'guard_pixels':2,'key_source_guard':4,'stable_guard':32,'fusion':'union','elapsed_seconds':time.monotonic()-started,'sheets':sheets,'frames':records}
        (root/'manifest.json').write_text(json.dumps(result,indent=2)+'\n');check_storage(root);(root/'INCOMPLETE').unlink()
    finally:
        for proc in streams:
            if proc.poll() is None:
                os.killpg(proc.pid,signal.SIGTERM)
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid,signal.SIGKILL);proc.wait(timeout=5)


if __name__=='__main__':main()
