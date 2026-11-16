#!/usr/bin/env python3
"""Compare two saved, unaligned ERP evaluations with verified source identity."""
import argparse
import json
from pathlib import Path
import cv2
import numpy as np
from evaluate_spherical_renders import frame_metrics,load_image


def calculate(pair):
    baseline=Path(pair['baseline_dataset']);excluded=Path(pair['exclusion_dataset']);names=json.loads((baseline/'manifest.json').read_text())['names'][::8]; mapping=json.loads((excluded/'manifest.json').read_text())['frames'][::8]
    if names!=[f['source_name'] for f in mapping]:raise ValueError('Holdout camera identities differ')
    # Resolve by option, independently of command argument order.
    runs=[Path(pair['commands'][k][pair['commands'][k].index('--output-dir-prefix')+1])/pair['commands'][k][pair['commands'][k].index('--output-dir-name')+1] for k in ('baseline','exclude_three')]
    metrics=[json.loads((r/'metrics.json').read_text()) for r in runs]
    rows=[]
    for i,name in enumerate(names):
        refs=[load_image(r/f'eval-gt-{i:05}.png') for r in runs];masks=[load_image(r/f'eval-mask-{i:05}.png',True) for r in runs]
        if not np.array_equal(refs[0],refs[1]) or not np.array_equal(masks[0],masks[1]):raise ValueError(f'Ground truth or masks differ for {name}')
        src=load_image(baseline/'images'/name)
        if not np.array_equal(refs[0][masks[0]>=128],src[masks[0]>=128]):raise ValueError(f'Ground truth does not match {name}')
        row={'index':i,'source_name':name,'source_frame':mapping[i]['source_frame'],'time_seconds':mapping[i]['time_seconds']}
        for arm,run,metric in zip(('baseline','exclude_three'),runs,metrics):
            values=frame_metrics(refs[0],load_image(run/f'eval-render-{i:05}.png'),masks[0]);s=values['spherical']
            row[arm]={'weighted_psnr_db':s['weighted_psnr_db'],'pixel_psnr_db':values['pixel_psnr_db'],'gradient_ratio':s['gradient_ratio'],'masked_ssim':metric['masked_ssim'][i]}
        row['delta_weighted_psnr_db']=row['exclude_three']['weighted_psnr_db']-row['baseline']['weighted_psnr_db'];rows.append(row)
    return rows,runs


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('pair_manifest',type=Path);p.add_argument('output',type=Path);a=p.parse_args();rows,runs=calculate(json.loads(a.pair_manifest.read_text()));ordered=sorted(rows,key=lambda r:r['delta_weighted_psnr_db']);chosen=[ordered[0],ordered[len(ordered)//2],ordered[-1]];panels=[]
    for row in chosen:
        i=row['index']
        for label,path in [('Reference',runs[0]/f'eval-gt-{i:05}.png'),('All cameras',runs[0]/f'eval-render-{i:05}.png'),('Three excluded',runs[1]/f'eval-render-{i:05}.png')]:
            img=load_image(path);cv2.rectangle(img,(0,0),(img.shape[1],30),(0,0,0),-1);cv2.putText(img,f'{row["source_name"]} {label}',(6,22),cv2.FONT_HERSHEY_SIMPLEX,.65,(255,255,255),1,cv2.LINE_AA);panels.append(img)
    a.output.mkdir();(a.output/'metrics.json').write_text(json.dumps({'method':'unaligned and uncorrected, identical saved native ERP references and masks','frames':rows},indent=2,allow_nan=False)+'\n')
    if not cv2.imwrite(str(a.output/'comparison.png'),np.concatenate(panels,axis=0)):raise OSError('Could not write sheet')
if __name__=='__main__':main()
