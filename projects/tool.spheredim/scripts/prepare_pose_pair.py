#!/usr/bin/env python3
"""Prepare two no-warp training commands with identical source holdouts; do not launch."""
import argparse
import hashlib
import json
from pathlib import Path


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def validate_pair(baseline,excluded):
    b=baseline['names'];e=excluded['frames']
    if len(b)!=133 or len(e)!=130 or len({x['name'] for x in e})!=130:raise ValueError('Unexpected camera count')
    if [x['source_name'] for x in e[::8]] != b[::8]:raise ValueError('Holdout source identities differ')
    if any(x['split']!=('heldout' if i%8==0 else 'train') for i,x in enumerate(e)):raise ValueError('Split labels differ')
    if set(b)-{x['source_name'] for x in e} != {'frame_001320.png','frame_001335.png','frame_001800.png'}:raise ValueError('Unexpected excluded frames')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('baseline_dataset',type=Path);p.add_argument('exclusion_dataset',type=Path);p.add_argument('baseline_run',type=Path);p.add_argument('executable',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
    base,excl,old,binary=(v.resolve(strict=True) for v in (a.baseline_dataset,a.exclusion_dataset,a.baseline_run,a.executable));bm=json.loads((base/'manifest.json').read_text());em=json.loads((excl/'manifest.json').read_text());cfg=json.loads((old/'config.json').read_text());validate_pair(bm,em)
    if cfg['eval_mode']!='interval' or cfg['eval_interval']!=8:raise ValueError('Unexpected baseline split')
    if sha(binary)!=em['executable_sha256'] or sha(base/'seed.ply')!=em['seed_sha256']:raise ValueError('Executable or seed differs')
    for frame in em['frames']:
        for folder in ('images','masks'):
            if not (excl/folder/frame['name']).samefile(base/folder/frame['source_name']):raise ValueError('Image or mask is not the baseline file')
    common=['train','360-camera','--seed-pointcloud','seed.ply','--num-iterations','3000','--steps-per-save','1000','--save-full-checkpoint','1','--disable-viewer','1','--cap-max','300000','--min-init-fraction','0','--sampling-seed','42','--load-masks','1','--apply-loss-for-mask','0','--flip-mask','0','--warp-spherical-to-pinhole','0','--warp-to-pinhole','0','--eval-mode','interval','--eval-interval','8','--eval-lpips','0','--save-eval-images','1','--auto-scale-poses','0','--scene-center','none','--calib-correction','off','--use-calib-warp','0','--perceptual-loss','ssim','--eval-align','0']
    outdir=a.output.resolve().parent
    def cmd(dataset,name):return [str(binary),*common,'--data',str(dataset),'--output-dir-prefix',str(outdir),'--output-dir-name',name]
    result={'status':'prepared for review; no training launched','hypothesis':'Removing three suspect SfM training poses changes reconstruction quality at the identical 17 held-out cameras.','camera_difference':'133 vs 130 input cameras; 116 vs 113 training. Sampling schedules and train indices differ.','controls':'Fresh runs; same source images, poses, seed, masks, resolution, holdouts, seed 42, cap, steps, no calibration warp and ordinary SSIM. No fitted evaluation alignment.', 'warning':'Diagnostic only: known ERP seam and mask boundary behavior is not fixed, and heldout cameras contributed to SfM and seed.', 'heldout_source_names':bm['names'][::8],'baseline_dataset':str(base),'exclusion_dataset':str(excl),'exclusion_manifest_sha256':sha(excl/'manifest.json'),'baseline_manifest_sha256':sha(base/'manifest.json'),'baseline_config_sha256':sha(old/'config.json'),'executable_sha256':sha(binary),'seed_sha256':sha(base/'seed.ply'),'commands':{'baseline':cmd(base,'pose-ab-unfiltered-no-warp'),'exclude_three':cmd(excl,'pose-ab-exclude-three-no-warp')},'resource_policy':{'max_incremental_output_bytes':2*1024**3,'minimum_free_bytes':35*1024**3,'monitor_interval_seconds':30}}
    with a.output.open('x') as f:json.dump(result,f,indent=2);f.write('\n')
if __name__=='__main__':main()
