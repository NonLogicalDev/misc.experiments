#!/usr/bin/env python3
"""Build a separate viewer state from a COLMAP ERP model and reviewed timestamps."""
import argparse
import hashlib
import json
import math
import os
import re
from pathlib import Path


def read_poses(path):
    # COLMAP images.txt has one pose line followed by one (possibly empty) observation line.
    lines = [line for line in path.read_text().splitlines() if not line.startswith('#')]
    if len(lines) % 2:
        raise ValueError('COLMAP image records require pose and observation lines')
    result = {}
    for line in lines[::2]:
        fields = line.split()
        if len(fields) != 10:
            raise ValueError(f'Invalid pose record: {line}')
        w, x, y, z = map(float, fields[1:5]); tx, ty, tz = map(float, fields[5:8])
        norm = math.sqrt(w*w+x*x+y*y+z*z)
        if not math.isfinite(norm) or abs(norm-1) > 1e-6 or not all(map(math.isfinite, (tx,ty,tz))):
            raise ValueError('Non-unit quaternion or non-finite translation')
        # COLMAP stores camera-from-world rotation and translation; invert both.
        r = [[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
             [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
             [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]]
        t = (tx, ty, tz)
        matrix = [[r[j][i] for j in range(3)] + [-sum(r[j][i]*t[j] for j in range(3))] for i in range(3)]
        name = fields[9]
        if name in result: raise ValueError(f'Duplicate image: {name}')
        result[name] = matrix
    return result


def build_frames(poses, dataset, reviewed):
    names = dataset['names']
    if len(names) != dataset['camera_count'] or len(set(names)) != len(names) or set(names) != set(poses):
        raise ValueError('Dataset camera list and COLMAP poses do not match')
    rows = reviewed['frames']; times = {row['source_frame']: row['video_pts_s'] for row in rows}
    if len(times) != len(rows): raise ValueError('Duplicate reviewed source frame')
    mapped = {row['name']:row for row in dataset.get('frames',[])}
    if mapped and set(mapped)!=set(names): raise ValueError('Frame mapping and camera names differ')
    frames = []
    for i, name in enumerate(names):
        source_name = mapped[name]['source_name'] if mapped else name
        if not source_name.startswith('frame_') or not source_name.endswith('.png') or not source_name[6:-4].isdigit():
            raise ValueError(f'Unexpected source frame name: {source_name}')
        source_frame = int(source_name[6:-4]); timestamp = times[source_frame]
        if mapped and (mapped[name]['source_frame']!=source_frame or mapped[name]['time_seconds']!=timestamp): raise ValueError('Source mapping mismatch')
        if not math.isfinite(timestamp): raise ValueError('Invalid timestamp')
        frames.append({'frame': i, 'source_frame': source_frame, 'image': name,
                       'time_seconds': timestamp, 'split': 'heldout' if i % 8 == 0 else 'train',
                       'world_from_camera': poses[name]})
    frames.sort(key=lambda f:f['time_seconds'])
    if any(a['time_seconds'] >= b['time_seconds'] for a, b in zip(frames, frames[1:])):
        raise ValueError('Frames must have strictly increasing timestamps')
    return frames


def estimate_up(frames):
    axes=[[-row[1] for row in frame['world_from_camera']] for frame in frames]
    mean=[sum(axis[i] for axis in axes)/len(axes) for i in range(3)]
    norm=math.sqrt(sum(x*x for x in mean))
    if norm < 1e-9: raise ValueError('Camera up directions cancel')
    up=[x/norm for x in mean]
    angles=sorted(math.degrees(math.acos(max(-1.,min(1.,sum(a*b for a,b in zip(axis,up)))))) for axis in axes)
    def percentile(p):
        position=(len(angles)-1)*p; low=int(position); high=min(low+1,len(angles)-1)
        return angles[low]+(position-low)*(angles[high]-angles[low])
    return up, {'method':'normalized mean of camera-to-world negative Y axes', 'median_degrees':percentile(.5), 'p90_degrees':percentile(.9), 'max_degrees':angles[-1]}


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024*1024), b''): h.update(chunk)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset', type=Path); parser.add_argument('run', type=Path)
    parser.add_argument('reviewed_manifest', type=Path); parser.add_argument('reference_video', type=Path)
    parser.add_argument('output', type=Path, help='New output directory')
    parser.add_argument('--checkpoint', help='Checkpoint directory name; default is the configured final step')
    args = parser.parse_args()
    dataset, run, reviewed, video = (p.resolve(strict=True) for p in (args.dataset,args.run,args.reviewed_manifest,args.reference_video))
    dataset_manifest=dataset/'manifest.json'; images=dataset/'sparse/0/images.txt'; transform=run/'scene_transform.json'
    review_data=json.loads(reviewed.read_text()); config=json.loads((run/'config.json').read_text())
    if (reviewed.parent/review_data['source']).resolve() != video:
        raise ValueError('Reference video differs from reviewed stabilized source')
    if config['eval_mode'] != 'interval' or config['eval_interval'] != 8:
        raise ValueError('Expected the recorded interval-8 split')
    camera=(dataset/'sparse/0/cameras.txt').read_text().split()
    if len(camera)!=6 or camera[0]!='1' or camera[1]!='EQUIRECTANGULAR' or not all(x.isdigit() for x in camera[2:]): raise ValueError('Unexpected camera model')
    width,height=map(int,camera[2:4])
    if width!=2*height or list(map(int,camera[4:]))!=[width,height]: raise ValueError('Unexpected ERP dimensions')
    checkpoint=args.checkpoint or f"step-{config['num_iterations']:09d}.ckpt"
    match=re.fullmatch(r'step-(\d+)\.ckpt',checkpoint)
    if not match: raise ValueError('Invalid checkpoint name')
    step=int(match.group(1)); splat=run/checkpoint/'splat.ply'
    frames=build_frames(read_poses(images),json.loads(dataset_manifest.read_text()),review_data)
    if not video.is_file() or not splat.is_file(): raise ValueError('Reference video or checkpoint missing')
    up, up_evidence=estimate_up(frames)
    matrix=json.loads(transform.read_text())['world_from_train']['matrix_4x4']
    if len(matrix)!=4 or any(len(row)!=4 or not all(map(math.isfinite,row)) for row in matrix): raise ValueError('Invalid scene transform')
    # Resolve paths in the state independently of the process working directory.
    output=args.output.resolve()
    relative=lambda p: os.path.relpath(p,output)
    seed=dataset/'seed.ply'
    if not seed.is_file(): raise ValueError('SfM seed point cloud missing')
    state={'version':1, 'trajectory':{'poses':'poses.json','points':relative(seed)}, 'up':up,
           'artifacts':{'splat':{'file':relative(splat),'transform':relative(transform),'run':relative(run),'checkpoint':splat.parent.name}},
           'reference':{'file':relative(video),'label':'Stabilized source panorama'},
           'stages':[{'name':'Gaussian training','status':'complete','current':step,'total':config['num_iterations']}], 'currentActivity':0,
           'details':[f'{len(frames)} selected native ERP cameras; held-out frames also contributed to SfM poses and seed.',
                      f'{step:,}-step SfM checkpoint.']}
    # Exclusive output prevents accidental replacement of an existing profile or viewer state.
    args.output.mkdir()
    def write(name, obj): (args.output/name).write_text(json.dumps(obj,indent=2,allow_nan=False)+'\n')
    write('poses.json',{'schema':'spheredim-viewer-poses-v1','coordinates':'COLMAP camera-to-world, x right y down z forward','frames':frames})
    write('viewer-state.json',state)
    write('manifest.json',{'dataset_manifest':str(dataset_manifest),'reviewed_manifest':str(reviewed),
          'colmap_images':str(images),'scene_transform':str(transform),'checkpoint':str(splat),'reference_video':str(video),
          'sha256':{str(p):digest(p) for p in (dataset_manifest,reviewed,images,transform,splat,seed)},
          'camera_count':len(frames),'image_width':width,'image_height':height,'checkpoint_step':step,'train_count':sum(f['split']=='train' for f in frames),
          'heldout_count':sum(f['split']=='heldout' for f in frames),
          'split_rule':'sorted dataset camera index modulo 8; pose and seed used all frames',
          'up':up, 'up_estimate':up_evidence, 'sparse_points':str(seed),
          'frames':[{key:frame[key] for key in ('frame','source_frame','image','time_seconds','split')} for frame in frames]})


if __name__=='__main__': main()
