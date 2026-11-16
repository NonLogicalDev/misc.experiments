#!/usr/bin/env python3
"""Score saved native ERP held-out splat renders against verified input images."""
import argparse
import hashlib
import json
import re
from pathlib import Path
import sys
import cv2
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
import evaluate_spherical_renders as metrics


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


def mapping(manifest,run):
    names=manifest['heldout_evaluation_order'];rows=manifest['frames'];byname={r['name']:r for r in rows}
    if len(byname)!=len(rows) or names!=sorted(names) or len(set(names))!=len(names) or set(names)!={r['name'] for r in rows if r['split']=='eval'}:raise ValueError('Invalid held-out camera mapping')
    result=[]
    for kind in ('gt','render','mask'):
        actual={p.name for p in run.glob(f'eval-{kind}-*.png')};expected={f'eval-{kind}-{i:05d}.png' for i in range(len(names))}
        if actual!=expected:raise ValueError(f'Incomplete or unexpected {kind} render files')
    for i,name in enumerate(names):
        row=byname[name]
        result.append((i,row,run/f'eval-gt-{i:05d}.png',run/f'eval-render-{i:05d}.png',run/f'eval-mask-{i:05d}.png'))
    return result


def spherical_ssim(reference,rendered,mask):
    a=reference.astype(np.float64)/255.;b=rendered.astype(np.float64)/255.;keep=mask>=128
    # 11x11 Gaussian SSIM, only windows entirely within valid mask.
    valid=cv2.erode(keep.astype(np.uint8),np.ones((11,11),np.uint8),borderType=cv2.BORDER_CONSTANT,borderValue=0).astype(bool)
    if not valid.any():raise ValueError('No complete SSIM windows')
    blur=lambda x:cv2.GaussianBlur(x,(11,11),1.5,borderType=cv2.BORDER_REFLECT_101)
    ma,mb=blur(a),blur(b);va=blur(a*a)-ma*ma;vb=blur(b*b)-mb*mb;cab=blur(a*b)-ma*mb
    s=((2*ma*mb+.01**2)*(2*cab+.03**2))/((ma*ma+mb*mb+.01**2)*(va+vb+.03**2));h=mask.shape[0];weight=valid*np.cos((np.arange(h)+.5-h/2)*np.pi/h)[:,None]
    return float((s.mean(axis=2)*weight).sum()/weight.sum())


def difference(a,b):
    return None if a is None or b is None else b-a


def psnr_label(value):
    return 'perfect' if value is None else f'{value:.2f} dB'


def compare_reports(previous,current,baseline_label,current_label):
    a=previous['frames'];b=current['frames']
    if len(a)!=len(b):raise ValueError('Comparison frame count differs')
    keys=('index','name','source_name','source_frame','lens','timestamp_microseconds','input_sha256','gt_sha256','mask_sha256')
    if any(any(x.get(k)!=y.get(k) for k in keys) for x,y in zip(a,b)):raise ValueError('Comparison identity or reference mismatch')
    return {'baseline_label':baseline_label,'current_label':current_label,'method':'Identical held-out views, masks and reference pixels; no alignment or filtering.',
            'mean_spherical_psnr_delta_db':difference(previous['summary']['mean_spherical_psnr_db'],current['summary']['mean_spherical_psnr_db']),
            'mean_spherical_ssim_delta':current['summary']['mean_spherical_ssim']-previous['summary']['mean_spherical_ssim'],
            'mean_gradient_ratio_delta':difference(previous['summary']['mean_gradient_ratio'],current['summary']['mean_gradient_ratio']),
            'per_frame':[{'name':y['name'],'spherical_psnr_delta_db':difference(x['spherical']['weighted_psnr_db'],y['spherical']['weighted_psnr_db']),'spherical_ssim_delta':y['spherical_ssim']-x['spherical_ssim']} for x,y in zip(a,b)]}


def evaluate(manifest_path,run,output,sheet,doorway=None,compare_to=None,label=None,baseline_label=None):
    if output.exists() or sheet.exists():raise FileExistsError('Report and sheet must be new')
    manifest=json.loads(manifest_path.read_text());dataset=manifest_path.parent;matched=mapping(manifest,run);rows=[]
    for i,r,gt_path,pred_path,mask_path in matched:
        source=metrics.load_image(dataset/'images'/r['name']);expected_mask=metrics.load_image(dataset/'masks'/r['name'],True);gt=metrics.load_image(gt_path);pred=metrics.load_image(pred_path);mask=metrics.load_image(mask_path,True)
        if source.shape!=(512,1024,3) or expected_mask.shape!=(512,1024) or gt.shape!=source.shape or pred.shape!=source.shape or mask.shape!=expected_mask.shape:raise ValueError(f'Dimensions mismatch: {r["name"]}')
        delta=np.abs(source.astype(np.int16)-gt.astype(np.int16));max_delta=int(delta.max())
        if max_delta>1 or not np.array_equal(mask,expected_mask):raise ValueError(f'Source or mask mismatch at index {i}: max source delta {max_delta}')
        row={'index':i,'name':r['name'],'source_name':r['source_name'],'source_frame':r['source_frame'],'lens':r['lens'],'timestamp_microseconds':r['timestamp_microseconds'],'reference_max_channel_difference':max_delta,'mask_exact':True,'input_sha256':digest(dataset/'images'/r['name']),'gt_sha256':digest(gt_path),'render_sha256':digest(pred_path),'mask_sha256':digest(mask_path),**metrics.frame_metrics(gt,pred,mask)}
        row['spherical_ssim']=spherical_ssim(gt,pred,mask);rows.append(row)
    ordered=sorted(rows,key=lambda x:float('inf') if x['spherical']['weighted_psnr_db'] is None else x['spherical']['weighted_psnr_db']);chosen=[('worst',ordered[0]),('median',ordered[len(ordered)//2]),('best',ordered[-1])]
    if doorway is not None:
        for lens in ('cam0','cam1'):
            matches=[r for r in rows if r['source_frame']==doorway and r['lens']==lens]
            if len(matches)!=1:raise ValueError(f'Doorway frame {doorway} {lens} is not held out')
            if not any(x['index']==matches[0]['index'] for _,x in chosen):chosen.append((f'frame {doorway} {lens}',matches[0]))
    tiles=[]
    for selection_label,row in chosen:
        i=row['index'];gt=metrics.load_image(run/f'eval-gt-{i:05d}.png');pred=metrics.load_image(run/f'eval-render-{i:05d}.png');tile=np.concatenate([cv2.resize(gt,(512,256)),cv2.resize(pred,(512,256))],axis=1);cv2.rectangle(tile,(0,0),(1023,26),(0,0,0),-1);cv2.putText(tile,f'{selection_label}: {row["name"]}   source left / render right   PSNR {psnr_label(row["spherical"]["weighted_psnr_db"])}',(5,18),cv2.FONT_HERSHEY_SIMPLEX,.48,(255,255,255),1,cv2.LINE_AA);tiles.append(tile)
    sheet_data=cv2.imencode('.png',np.concatenate(tiles,axis=0))[1].tobytes()
    if len(sheet_data)>19*1024**2:raise RuntimeError('Contact sheet exceeds evaluation budget')
    vals=lambda key:[r[key] for r in rows];psnr=[r['spherical']['weighted_psnr_db'] for r in rows if r['spherical']['weighted_psnr_db'] is not None];gradient=[r['spherical']['gradient_ratio'] for r in rows if r['spherical']['gradient_ratio'] is not None]
    checkpoints=[]
    for path in run.glob('step-*.ckpt/splat.ply'):
        match=re.fullmatch(r'step-(\d+)\.ckpt',path.parent.name)
        if match and path.is_file():checkpoints.append((int(match.group(1)),path))
    checkpoint=max(checkpoints,default=None,key=lambda x:x[0]);config=run/'config.json';status=run.parent/(run.name+'.status.json')
    associated={'run':str(run.resolve()),'checkpoint':({'step':checkpoint[0],'file':str(checkpoint[1].resolve()),'sha256':digest(checkpoint[1])} if checkpoint else None),'config':({'file':str(config.resolve()),'sha256':digest(config)} if config.is_file() else None),'status':({'file':str(status.resolve()),'sha256':digest(status)} if status.is_file() else None)}
    report={'associated_run_artifacts':associated,'method':'Filename-ordered held-out lens images; exact saved mask and reference pixels checked against input; spherical area-weighted RGB PSNR and 11x11 Gaussian SSIM on complete valid windows; unaligned; 3DGS-only holdout, these views contributed to SfM.','checkpoint_provenance':'Saved render files are hashed; their generation from a particular checkpoint is not independently verified by this evaluator. Null PSNR denotes an exact pixel match; PSNR deltas involving an exact match are null.','manifest_sha256':digest(manifest_path),'script_sha256':digest(Path(__file__)),'metrics_sha256':digest(Path(metrics.__file__)),'summary':{'frames':len(rows),'mean_spherical_psnr_db':float(np.mean(psnr)) if psnr else None,'median_spherical_psnr_db':float(np.median(psnr)) if psnr else None,'perfect_spherical_frames':len(rows)-len(psnr),'mean_spherical_ssim':float(np.mean(vals('spherical_ssim'))),'mean_gradient_ratio':float(np.mean(gradient)) if gradient else None},'contact_sheet':[{'selection':label,'index':row['index'],'name':row['name']} for label,row in chosen],'frames':rows}
    if compare_to is not None:
        if not label or not baseline_label:raise ValueError('Comparison requires both labels')
        previous=json.loads(compare_to.read_text());report['comparison']=compare_reports(previous,report,baseline_label,label);report['comparison']['baseline_report_sha256']=digest(compare_to)
    text=(json.dumps(report,indent=2,allow_nan=False)+'\n').encode()
    if len(sheet_data)+len(text)>20*1024**2:raise RuntimeError('Evaluation exceeds budget')
    with output.open('xb') as f:f.write(text)
    with sheet.open('xb') as f:f.write(sheet_data)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('manifest',type=Path);p.add_argument('run',type=Path);p.add_argument('report',type=Path);p.add_argument('sheet',type=Path);p.add_argument('--doorway-frame',type=int);p.add_argument('--compare-to',type=Path);p.add_argument('--label');p.add_argument('--baseline-label');a=p.parse_args();d=evaluate(a.manifest,a.run,a.report,a.sheet,a.doorway_frame,a.compare_to,a.label,a.baseline_label);print(json.dumps(d['summary'],indent=2))
if __name__=='__main__':main()
