#!/usr/bin/env python3
"""Prepare a fresh interval-split SfM dataset excluding specified training cameras."""
import argparse
import hashlib
import json
import os
from pathlib import Path

BAD=('frame_001320.png','frame_001335.png','frame_001800.png')


def reorder(names, excluded=BAD):
    if len(set(names))!=len(names) or names!=sorted(names): raise ValueError('Original names must be unique and sorted')
    held=names[::8]
    if len(set(excluded))!=len(excluded) or any(x not in names or x in held for x in excluded): raise ValueError('Exclude only distinct original training cameras')
    train=iter(x for i,x in enumerate(names) if i%8 and x not in excluded); hold=iter(held); n=len(names)-len(excluded)
    order=[next(hold) if i%8==0 else next(train) for i in range(n)]
    if order[::8]!=held: raise ValueError('Cannot preserve the interval split at this dataset size')
    return order


def parse_records(path):
    lines=[line for line in path.read_text().splitlines() if not line.startswith('#')]
    if len(lines)%2:raise ValueError('Expected paired COLMAP pose and observation lines')
    records={}
    for pose,observations in zip(lines[::2],lines[1::2]):
        fields=pose.split()
        if len(fields)!=10 or fields[9] in records:raise ValueError('Invalid or duplicate COLMAP pose')
        records[fields[9]]=(fields,observations)
    return records


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('dataset',type=Path);p.add_argument('baseline_run',type=Path);p.add_argument('reviewed_manifest',type=Path);p.add_argument('executable',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
    ds=a.dataset.resolve(strict=True);run=a.baseline_run.resolve(strict=True);review=a.reviewed_manifest.resolve(strict=True);binary=a.executable.resolve(strict=True)
    meta=json.loads((ds/'manifest.json').read_text());cfg=json.loads((run/'config.json').read_text());names=meta['names'];order=reorder(names);records=parse_records(ds/'sparse/0/images.txt')
    reviewed=json.loads(review.read_text())['frames'];times={f['source_frame']:f['video_pts_s'] for f in reviewed}
    if len(names)!=133 or len(order)!=130 or set(records)!=set(names) or len(times)!=len(reviewed): raise ValueError('Unexpected source dataset')
    if cfg['eval_mode']!='interval' or cfg['eval_interval']!=8:raise ValueError('Baseline split differs')
    if (ds/'sparse/0/cameras.txt').read_text().split()!=['1','EQUIRECTANGULAR','1024','512','1024','512']:raise ValueError('Unexpected camera model')
    if any(not (ds/d/n).is_file() for d in ('images','masks') for n in names):raise ValueError('Missing source image or mask')
    out=a.output.resolve();out.mkdir();(out/'images').mkdir();(out/'masks').mkdir();(out/'sparse/0').mkdir(parents=True)
    def link(src,dst):dst.symlink_to(os.path.relpath(src,dst.parent))
    for name in ('cameras.txt','points3D.txt'):link(ds/'sparse/0'/name,out/'sparse/0'/name)
    link(ds/'seed.ply',out/'seed.ply');mapping=[];lines=[]
    for i,old in enumerate(order):
        new=f'{i:06d}_{old}';fields,obs=records[old];source_frame=int(old[6:-4]);fields=fields.copy();fields[9]=new
        for d in ('images','masks'):link(ds/d/old,out/d/new)
        lines.append(' '.join(fields)+'\n'+obs+'\n')
        mapping.append({'index':i,'name':new,'source_name':old,'source_frame':source_frame,'time_seconds':times[source_frame],'source_colmap_image_id':int(fields[0]),'split':'heldout' if i%8==0 else 'train'})
    (out/'sparse/0/images.txt').write_text(''.join(lines))
    cmd=[str(binary),'train','360-camera','--data',str(out),'--output-dir-prefix',str(out.parent),'--output-dir-name','UNSET_NEW_RUN_NAME','--seed-pointcloud','seed.ply','--num-iterations','3000','--steps-per-save','1000','--save-full-checkpoint','1','--disable-viewer','1','--cap-max','300000','--min-init-fraction','0','--sampling-seed','42','--load-masks','1','--apply-loss-for-mask','0','--flip-mask','0','--warp-spherical-to-pinhole','0','--warp-to-pinhole','0','--eval-mode','interval','--eval-interval','8','--eval-lpips','0','--save-eval-images','1','--auto-scale-poses','0','--scene-center','none']
    manifest={'status':'prepared; no training launched','camera_count':130,'train_count':113,'heldout_count':17,'names':[m['name'] for m in mapping],'frames':mapping,'excluded_training_names':list(BAD),'baseline_dataset':str(ds),'baseline_run':str(run),'reviewed_manifest':str(review),'baseline_config_sha256':digest(run/'config.json'),'source_manifest_sha256':digest(ds/'manifest.json'),'source_images_txt_sha256':digest(ds/'sparse/0/images.txt'),'seed_sha256':digest(ds/'seed.ply'),'executable_sha256':digest(binary),'command_template':cmd,'note':'Fresh training only; split preserved by sorting renamed source images. Full original trajectory and inputs remain unchanged.'}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
if __name__=='__main__':main()
