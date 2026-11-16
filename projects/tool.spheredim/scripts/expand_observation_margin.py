#!/usr/bin/env python3
"""Expand a post-stabilization ERP invalid mask by angular distance."""
import argparse, hashlib, json, math, subprocess
from pathlib import Path
import numpy as np
from PIL import Image
from scipy.ndimage import maximum_filter1d


def angular_dilate(invalid, degrees):
    if invalid.ndim != 2 or not 0 <= degrees < 90: raise ValueError('invalid mask or angular margin')
    if degrees == 0: return invalid.copy()
    h,w=invalid.shape
    latitude=np.pi/2-(np.arange(h)+0.5)*np.pi/h
    radius=math.radians(degrees)
    out=invalid.copy()
    max_dy=min(h-1, math.floor(radius*h/math.pi))
    for dy in range(-max_dy,max_dy+1):
        target=np.arange(max(0,-dy),min(h,h-dy)); source=target+dy
        target=target[np.any(invalid[source],axis=1)]; source=target+dy
        if not len(target): continue
        a,b=latitude[target],latitude[source]
        t=(math.cos(radius)-np.sin(a)*np.sin(b))/(np.cos(a)*np.cos(b))
        widths=np.floor(np.arccos(np.clip(t-1e-12,-1,1))*w/(2*np.pi)+1e-9).astype(int)
        widths[t>1+1e-12]= -1
        for r in np.unique(widths):
            if r < 0: continue
            selection=widths==r
            # A full turn includes every longitude.
            size=min(2*int(r)+1,2*w+1)
            out[target[selection]] |= maximum_filter1d(invalid[source[selection]],size=size,axis=1,mode='wrap')
    return out


def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--input',type=Path,required=True); p.add_argument('--output',type=Path,required=True); p.add_argument('--degrees',type=float,required=True); p.add_argument('--only-frame',type=int); a=p.parse_args()
    if a.output.exists(): p.error('output must not exist')
    source=json.loads((a.input/'manifest.json').read_text()); indices=[a.only_frame] if a.only_frame is not None else list(range(source['first_frame'],source['first_frame']+source['frame_count']))
    expected={entry['path']:entry['sha256'] for entries in source['outputs'].values() for entry in entries}
    a.output.mkdir(parents=True)
    for name in ('color','validity','ownership'): (a.output/name).mkdir()
    frames=[]
    for index in indices:
        name=f'frame_{index:08}.png'
        for role in ('color','validity','ownership'):
            key=f'{role}/{name}'
            if expected.get(key) != digest(a.input/key): raise ValueError(f'source hash mismatch: {key}')
        color=np.asarray(Image.open(a.input/'color'/name).convert('RGB')).copy()
        mask=np.asarray(Image.open(a.input/'validity'/name).convert('RGB'))
        own=np.asarray(Image.open(a.input/'ownership'/name).convert('RGB')).copy()
        invalid=mask[:,:,0]==0
        if not np.all(mask == np.where(invalid[:,:,None],0,255)): raise ValueError('input mask is not binary')
        expanded=angular_dilate(invalid,a.degrees)
        if np.any(invalid & ~expanded): raise ValueError('lost invalid pixels')
        original=color.copy(); original_owner=own.copy()
        color[expanded]=0; own[expanded]=0
        if not np.array_equal(color[~expanded], original[~expanded]) or not np.array_equal(own[~expanded], original_owner[~expanded]): raise ValueError('retained observations changed')
        valid=(~expanded).astype(np.uint8)*255
        for role,arr in (('color',color),('validity',valid),('ownership',own)): Image.fromarray(arr).save(a.output/role/name)
        print(f'frame {index} ({len(frames)+1}/{len(indices)})', flush=True)
        frames.append({'frame':index,'invalid_pixels_before':int(invalid.sum()),'invalid_pixels_after':int(expanded.sum()),'images':{role:{'path':f'{role}/{name}','sha256':digest(a.output/role/name)} for role in ('color','validity','ownership')}})
    if a.only_frame is None:
        video=a.output/'observation.mp4'; subprocess.run(['ffmpeg','-v','error','-framerate','30000/1001','-start_number',str(indices[0]),'-i',str(a.output/'color/frame_%08d.png'),'-c:v','libx264rgb','-crf','0','-pix_fmt','rgb24',str(video)],check=True)
        def framehash(args):
            output=subprocess.check_output(['ffmpeg','-v','error',*args,'-pix_fmt','rgb24','-f','framemd5','-'],text=True)
            return [x.split(',')[-1].strip() for x in output.splitlines() if x and not x.startswith('#')]
        if framehash(['-framerate','30000/1001','-start_number',str(indices[0]),'-i',str(a.output/'color/frame_%08d.png')]) != framehash(['-i',str(video)]): raise ValueError('preview differs from PNG frames')
    manifest={'input_manifest':str((a.input/'manifest.json').resolve()),'input_manifest_sha256':digest(a.input/'manifest.json'),'input_observation_sha256':source['video_sha256'],'margin_degrees':a.degrees,'method':'great-circle angular distance between ERP pixel centers from invalid pixels; longitude wraps','exclusion_reason':'expanded existing validity exclusion, including provisional ownership crossover; not measured physical absence','frame_count':len(indices),'frames':frames,'source_timestamps':source['timestamps'] if a.only_frame is None else [x for x in source['timestamps'] if x['frame']==a.only_frame], 'preview_sha256':digest(video) if a.only_frame is None else None,'limitations':'Cut does not correct parallax or prove scene correspondence; source pixels outside expanded mask remain unchanged.'}
    (a.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')

if __name__ == '__main__': main()
