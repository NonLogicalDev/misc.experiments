#!/usr/bin/env python3
"""Prepare a paired-lens ERP splat dataset and reviewable command; never train."""
import argparse, hashlib, json, math, os, struct
from pathlib import Path


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for data in iter(lambda:f.read(1048576),b''): h.update(data)
    return h.hexdigest()


def read(f,fmt):
    n=struct.calcsize('<'+fmt); b=f.read(n)
    if len(b)!=n: raise ValueError('Truncated COLMAP file')
    return struct.unpack('<'+fmt,b)


def read_model(model):
    cameras=[]
    with (model/'cameras.bin').open('rb') as f:
        n,=read(f,'Q')
        for _ in range(n):
            i,kind,w,h=read(f,'iiQQ')
            if kind!=17 or w!=2*h: raise ValueError('Expected native equirectangular camera')
            a,b=read(f,'2d'); cameras.append((i,w,h,a,b))
        if f.read(1): raise ValueError('Unexpected camera bytes')
    poses=[]
    with (model/'images.bin').open('rb') as f:
        n,=read(f,'Q')
        for _ in range(n):
            row=read(f,'i7di');name=bytearray()
            while (c:=f.read(1))!=b'\0':
                if not c or len(name)>1024: raise ValueError('Invalid image name')
                name+=c
            count,=read(f,'Q');data=f.read(count*24)
            if len(data)!=count*24 or not all(math.isfinite(x) for x in row[1:8]):raise ValueError('Invalid image data')
            poses.append((name.decode(),row))
        if f.read(1):raise ValueError('Unexpected image bytes')
    points=[]
    with (model/'points3D.bin').open('rb') as f:
        n,=read(f,'Q')
        for _ in range(n):
            row=read(f,'Q3d3Bd');count,=read(f,'Q');data=f.read(count*8)
            if len(data)!=count*8 or not all(math.isfinite(x) for x in row[1:4]):raise ValueError('Invalid point')
            points.append((*row[1:4],*row[4:7]))
        if f.read(1):raise ValueError('Unexpected point bytes')
    return cameras,poses,points


def split_frames(frames,interval):
    frames=sorted(frames)
    if len(frames)<2 or len(frames)!=len(set(frames)) or interval<2:raise ValueError('Invalid frame selection')
    return {frame:('eval' if i%interval==0 else 'train') for i,frame in enumerate(frames)}


def validate_schedule(iterations,save_every):
    if not all(isinstance(x,int) and not isinstance(x,bool) for x in (iterations,save_every)) or not 1<=save_every<=iterations<=100000:
        raise ValueError('Iterations and save interval must be positive, save interval no greater than iterations, and iterations at most 100000')


def prepare(dataset,model,binary,out,run_name,interval=8,iterations=3000,save_every=1000,log_performance=False,unpacked=False,no_appearance_correction=False,eval_frames=None,save_full_checkpoint=True):
    validate_schedule(iterations,save_every)
    dataset,model,binary=map(lambda p:Path(p).resolve(strict=True),(dataset,model,binary));out=Path(out).resolve()
    if out.exists():raise ValueError('Output already exists')
    meta=json.loads((dataset/'manifest.json').read_text());frames=meta['frames'];frame_ids=[x['source_frame'] for x in frames]
    split=split_frames(frame_ids,interval)
    if eval_frames is not None:
        heldout=set(eval_frames)
        if not heldout or len(heldout)!=len(eval_frames) or not heldout < set(frame_ids):raise ValueError('Invalid explicit evaluation frames')
        split={frame:('eval' if frame in heldout else 'train') for frame in frame_ids}
    if not save_full_checkpoint and save_every!=iterations:raise ValueError('Compact checkpoint requires final-only save')
    cams,poses,points=read_model(model)
    if len(cams)!=2 or len(poses)!=len(frames)*2 or not points:raise ValueError('Incomplete two-camera model')
    if len({x[0] for x in poses})!=len(poses) or len({x[0] for x in cams})!=2:raise ValueError('Duplicate cameras or images')
    if any(row[8] not in {c[0] for c in cams} or abs(sum(v*v for v in row[1:5])-1)>1e-3 for _,row in poses):raise ValueError('Invalid pose quaternion or camera ID')
    if not run_name or Path(run_name).name!=run_name:raise ValueError('Run name must be a single path component')
    byframe={x['source_frame']:x for x in frames}; expected={f'{lens}/frame_{frame:06d}.png' for frame in split for lens in ('cam0','cam1')}
    if {p[0] for p in poses}!=expected:raise ValueError('Model images do not match complete paired source frames')
    if any((c[1],c[2])!=tuple(meta['resolution']) for c in cams):raise ValueError('Camera resolution mismatch')
    for name,row in poses:
        lens,filename=name.split('/');frame=int(filename[6:-4]);entry=byframe[frame]['lenses'][lens]
        for folder,key in [('images','image_sha256'),('masks','mask_sha256')]:
            p=dataset/folder/name
            if digest(p)!=entry[key]:raise ValueError(f'Input hash mismatch: {p}')
    out.mkdir();(out/'images').mkdir();(out/'masks').mkdir();(out/'sparse/0').mkdir(parents=True)
    records=[];lines=[]
    for name,row in sorted(poses):
        lens,filename=name.split('/');frame=int(filename[6:-4]);new=f'{split[frame]}_{frame:06d}_{lens}.png'
        for folder in ('images','masks'):os.link(dataset/folder/name,out/folder/new)
        lines.append(' '.join([str(row[0]),*[format(x,'.17g') for x in row[1:8]],str(row[8]),new])+'\n\n')
        records.append({'name':new,'source_name':name,'source_frame':frame,'lens':lens,'split':split[frame],'timestamp_microseconds':byframe[frame]['timestamp_microseconds'],'source_packet_pts':byframe[frame]['source_packet_pts'],'colmap_image_id':row[0],'colmap_camera_id':row[8]})
    (out/'sparse/0/cameras.txt').write_text(''.join(f'{i} EQUIRECTANGULAR {w} {h} {a:.17g} {b:.17g}\n' for i,w,h,a,b in cams))
    (out/'sparse/0/images.txt').write_text(''.join(lines));(out/'sparse/0/points3D.txt').write_text('# seed supplied as PLY\n')
    (out/'seed.ply').write_text('ply\nformat ascii 1.0\nelement vertex '+str(len(points))+'\nproperty float x\nproperty float y\nproperty float z\nproperty uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n'+''.join(' '.join(map(str,p))+'\n' for p in points))
    flags=['train','360-camera','--data',str(out),'--output-dir-prefix',str(out.parent),'--output-dir-name',run_name,'--seed-pointcloud','seed.ply','--num-iterations',str(iterations),'--steps-per-save',str(save_every),'--save-full-checkpoint','1' if save_full_checkpoint else '0','--disable-viewer','1','--cap-max','300000','--min-init-fraction','0','--sampling-seed','42','--load-masks','1','--apply-loss-for-mask','0','--flip-mask','0','--mask-boundary-offset','0','--warp-spherical-to-pinhole','0','--warp-to-pinhole','0','--eval-mode','filename','--eval-lpips','0','--save-eval-images','1','--auto-scale-poses','0','--orientation-method','none','--center-method','none','--scene-center','none','--calib-correction','off','--use-calib-warp','0','--perceptual-loss','ssim','--eval-align','0']
    if log_performance:flags.extend(['--log-performance','1'])
    if unpacked:flags.extend(['--packed','0'])
    if no_appearance_correction:flags.extend(['--use-bilateral-grid','0','--use-ppisp','0'])
    result={'status':'prepared for review; no training launched','dataset':str(dataset),'model':str(model),'model_hashes':{x:digest(model/x) for x in ('cameras.bin','images.bin','points3D.bin','rigs.txt')},'source_manifest_sha256':digest(dataset/'manifest.json'),'binary_sha256':digest(binary),'seed_sha256':digest(out/'seed.ply'),'camera_count':len(records),'point_count':len(points),'frames':records,'heldout_evaluation_order':[x['name'] for x in sorted(records,key=lambda x:x['name']) if x['split']=='eval'],'training_path_sample':[x['name'] for x in sorted(records,key=lambda x:x['name']) if x['split']=='train'][:4],'split_method':(f'every {interval}th sorted timestamp held out for BOTH physical lenses; filename-based eval' if eval_frames is None else 'explicit timestamps held out for BOTH physical lenses; filename-based eval'),'save_full_checkpoint':save_full_checkpoint,'training_path_evaluation':'Required for path-point quality acceptance; exact original training camera mapping remains to be implemented.','notes':['Camera poses retain fixed physical rig geometry from the source model; trainer consumes fixed per-image poses.','Source images and masks hardlinked without additional resampling. White mask means valid; images are already black outside support and reviewed operator mask.','Held-out observations contributed to the source SfM model and seed; evaluation is held out from splat training only.','ERP seam and mask boundary semantics remain under investigation.'],'command':[str(binary),*flags],'resource_policy':{'max_incremental_output_bytes':1024**3,'minimum_free_bytes':35*1024**3,'monitor_interval_seconds':10,'enforcement':'A storage watchdog is required before running; this manifest does not enforce limits.'}}
    (out/'manifest.json').write_text(json.dumps(result,indent=2)+'\n');return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('dataset',type=Path);p.add_argument('model',type=Path);p.add_argument('binary',type=Path);p.add_argument('output',type=Path);p.add_argument('--run-name',required=True);p.add_argument('--holdout-every',type=int,default=8);p.add_argument('--iterations',type=int,default=3000);p.add_argument('--save-every',type=int,default=1000);p.add_argument('--log-performance',action='store_true');p.add_argument('--unpacked',action='store_true',help='Experimental: store projections without packing');p.add_argument('--no-appearance-correction',action='store_true',help='Experimental: disable bilateral grid and PPISP');p.add_argument('--eval-frames-json',type=Path,help='JSON array of source frame indices held out for both lenses');p.add_argument('--compact-final-checkpoint',action='store_true',help='Omit optimizer state; requires --save-every equal to --iterations');a=p.parse_args();d=prepare(a.dataset,a.model,a.binary,a.output,a.run_name,a.holdout_every,a.iterations,a.save_every,a.log_performance,a.unpacked,a.no_appearance_correction,json.loads(a.eval_frames_json.read_text()) if a.eval_frames_json else None,not a.compact_final_checkpoint);print(f"Prepared {d['camera_count']} cameras and {d['point_count']} points; no training started")
if __name__=='__main__':main()
