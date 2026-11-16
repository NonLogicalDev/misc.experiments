#!/usr/bin/env python3
"""Map saved interval-8 ERP evaluations to source frames and measure them."""
import argparse
import json
from pathlib import Path
import cv2
import numpy as np
from evaluate_spherical_renders import frame_metrics, load_image


def check_pair(reference, mask, dataset_image, other_reference, other_mask):
    if not np.array_equal(reference, other_reference) or not np.array_equal(mask, other_mask):
        raise ValueError('The two arms use different ground truth or masks')
    valid=mask>=128
    if not np.array_equal(reference[valid], dataset_image[valid]):
        raise ValueError('Evaluation pixels do not match the selected dataset camera')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset',type=Path); parser.add_argument('reviewed_manifest',type=Path)
    parser.add_argument('sfm_run',type=Path); parser.add_argument('dvo_run',type=Path)
    parser.add_argument('output',type=Path,help='New output directory')
    args=parser.parse_args(); dataset=json.loads((args.dataset/'manifest.json').read_text()); reviewed=json.loads(args.reviewed_manifest.read_text())
    names=dataset['names']; times={x['source_frame']:x['video_pts_s'] for x in reviewed['frames']}
    if len(times)!=len(reviewed['frames']) or len(names)!=dataset['camera_count'] or len(set(names))!=len(names): raise ValueError('Duplicate or inconsistent frame manifest')
    for run in (args.sfm_run,args.dvo_run):
        config=json.loads((run/'config.json').read_text())
        if config['eval_mode']!='interval' or config['eval_interval']!=8: raise ValueError('Expected interval-8 evaluation')
    selected=names[::8]; rows=[]
    for i,name in enumerate(selected):
        ref=load_image(args.sfm_run/f'eval-gt-{i:05}.png'); mask=load_image(args.sfm_run/f'eval-mask-{i:05}.png',True)
        other=load_image(args.dvo_run/f'eval-gt-{i:05}.png'); other_mask=load_image(args.dvo_run/f'eval-mask-{i:05}.png',True)
        check_pair(ref,mask,load_image(args.dataset/'images'/name),other,other_mask)
        if not name.startswith('frame_') or not name.endswith('.png') or not name[6:-4].isdigit(): raise ValueError('Invalid source frame name')
        frame=int(name[6:-4]); row={'index':i,'frame':name,'source_frame':frame,'source_pts_s':times[frame]}
        for arm,run in (('sfm',args.sfm_run),('dvo',args.dvo_run)):
            values=frame_metrics(ref,load_image(run/f'eval-render-{i:05}.png'),mask)
            row[arm]={'pixel_psnr':values['pixel_psnr_db'],'weighted_psnr':values['spherical']['weighted_psnr_db'],'gradient_ratio':values['spherical']['gradient_ratio']}
        rows.append(row)
    ordered=sorted(rows,key=lambda row:row['sfm']['weighted_psnr'] if row['sfm']['weighted_psnr'] is not None else float('inf'))
    panels=[]
    for row in (ordered[0],ordered[len(ordered)//2],ordered[-1]):
        i=row['index']
        for label,path in (('reference',args.sfm_run/f'eval-gt-{i:05}.png'),('SfM',args.sfm_run/f'eval-render-{i:05}.png'),('DVO',args.dvo_run/f'eval-render-{i:05}.png')):
            image=load_image(path);cv2.rectangle(image,(0,0),(image.shape[1],30),(0,0,0),-1);cv2.putText(image,f'{row["frame"]}  {label}',(6,22),cv2.FONT_HERSHEY_SIMPLEX,.65,(255,255,255),1,cv2.LINE_AA);panels.append(image)
    args.output.mkdir()
    (args.output/'metrics.json').write_text(json.dumps({'method':'Saved masked ERP evaluation, no fitted alignment or color correction; dataset index = evaluation index × 8','frames':rows},indent=2,allow_nan=False)+'\n')
    if not cv2.imwrite(str(args.output/'comparison.png'),np.concatenate(panels,axis=0)): raise OSError('Failed to write contact sheet')

if __name__=='__main__':main()
