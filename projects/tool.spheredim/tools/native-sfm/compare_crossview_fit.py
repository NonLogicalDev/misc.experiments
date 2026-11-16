#!/usr/bin/env python3
"""Compare five fixed-capture renders before and after the same one-view fit."""
import argparse
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np
import compare_splat_pixels as pixels

# Rectangles are selected from the source captures, before examining either render.
REGIONS={
 'eval_001495_cam0.png':(1300,280,300,220),
 'eval_001495_cam1.png':(1450,280,200,280),
 'eval_001500_cam0.png':(1380,260,240,220),
 'eval_001505_cam0.png':(1370,240,250,220),
 'eval_001505_cam1.png':(1450,260,350,380),
}

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def new_bytes(path):return sum(f.stat().st_size for f in path.rglob('*') if f.is_file() and f.stat().st_nlink==1)

def compare(root):
    root=Path(root).resolve(strict=True);status=json.loads((root/'status.json').read_text());plan=json.loads((root/'crossview-plan.json').read_text());order=plan['eval_order']
    if any(status['runs'][k]['exit_code']!=0 or status['runs'][k]['reason'] for k in ('zero','fit')):raise ValueError('Diagnostic runs did not complete')
    transforms=[json.loads((root/k/'scene_transform.json').read_text())['train_from_world']['matrix_4x4'] for k in ('zero','fit')]
    if transforms[0]!=transforms[1] or not np.allclose(transforms[0],np.eye(4),rtol=0,atol=1e-12):raise ValueError('Scene transform mismatch')
    if set(order)!=set(REGIONS):raise ValueError('Unexpected evaluation capture order')
    output=[]
    for i,name in enumerate(order):
        src=pixels.load(root/'data/images'/name);mask=pixels.load(root/'data/masks'/name,True);zero=pixels.load(root/'zero'/f'eval-render-{i:05d}.png');fit=pixels.load(root/'fit'/f'eval-render-{i:05d}.png')
        for run in ('zero','fit'):
            if not np.array_equal(src,pixels.load(root/run/f'eval-gt-{i:05d}.png')) or not np.array_equal(mask,pixels.load(root/run/f'eval-mask-{i:05d}.png',True)):raise ValueError(f'Reference mismatch: {name}')
        x,y,w,h=REGIONS[name];valid=mask[y:y+h,x:x+w]>=128
        if not valid.any():raise ValueError(f'No valid ROI pixels: {name}')
        roi_src=src[y:y+h,x:x+w].astype(np.float64)/255;roi_zero=zero[y:y+h,x:x+w].astype(np.float64)/255;roi_fit=fit[y:y+h,x:x+w].astype(np.float64)/255
        z=float(np.mean((roi_zero[valid]-roi_src[valid])**2));f=float(np.mean((roi_fit[valid]-roi_src[valid])**2))
        score=pixels.score(src,zero,fit,mask,mask);summary=pixels.pool([score]);sheet_path=root/f'detail-{name[5:-4]}.png';header=np.zeros((24,3*w,3),np.uint8)
        for col,label in enumerate(('source','original 7k','one-view fit')):cv2.putText(header,label,(col*w+4,17),cv2.FONT_HERSHEY_SIMPLEX,.45,(255,255,255),1,cv2.LINE_AA)
        if sheet_path.exists():raise FileExistsError(sheet_path)
        if not cv2.imwrite(str(sheet_path),np.vstack((header,np.hstack([im[y:y+h,x:x+w] for im in (src,zero,fit)])))):raise IOError('Could not write sheet')
        if new_bytes(root)>30000000:raise ValueError('Output cap exceeded after sheet')
        output.append({'name':name,'roi_xywh':[x,y,w,h],'roi_valid_pixels':int(valid.sum()),'roi_zero_mse':z,'roi_fit_mse':f,'roi_mse_ratio':f/z if z else None,'full_frame':summary,'source_sha256':sha(root/'data/images'/name),'mask_sha256':sha(root/'data/masks'/name),'zero_sha256':sha(root/'zero'/f'eval-render-{i:05d}.png'),'fit_sha256':sha(root/'fit'/f'eval-render-{i:05d}.png'),'sheet_sha256':sha(sheet_path),'sheet':str(sheet_path)})
    report={'method':'Each ROI was selected using source pixels before viewing diagnostic renders. Full ERP frames and static slat ROIs use unchanged observed source and reviewed masks, no alignment or image adjustment. 1500 cam0 is the fitted capture; other four are neighboring training captures in original SfM, and all were in original model training. A fixed-state local experiment, not an independent pose test or overall reconstruction claim.','plan_sha256':sha(root/'crossview-plan.json'),'status_sha256':sha(root/'status.json'),'frames':output}
    path=root/'comparison.json';path.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n');print(json.dumps([{'name':r['name'],'roi_mse_ratio':r['roi_mse_ratio'],'spherical_mse_ratio':r['full_frame']['spherical_mse_ratio']} for r in output],indent=2))
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('staged');a=p.parse_args();compare(a.staged)
