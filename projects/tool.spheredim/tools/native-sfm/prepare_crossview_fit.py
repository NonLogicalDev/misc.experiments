#!/usr/bin/env python3
"""Stage one actual training capture and five fixed-camera evaluation captures."""
import argparse
import json
import os
from pathlib import Path
import prepare_capture_group as group


def stage(manifest,fit_plan,output):
    manifest=Path(manifest).resolve(strict=True);fit_plan=Path(fit_plan).resolve(strict=True);output=Path(output).resolve()
    train='train_001500_cam0.png';neighbors=[f'train_{frame:06}_cam{lens}.png' for frame in (1495,1505) for lens in (0,1)]
    evidence=group.prepare(manifest,output,[train],neighbors)
    data=output/'data';dup='eval_001500_cam0.png'
    for folder in ('images','masks'):os.link(data/folder/train,data/folder/dup)
    lines=(data/'sparse/0/images.txt').read_text().splitlines();row=next(x.split() for x in lines if x.split() and x.split()[-1]==train);row[0]='999';row[-1]=dup
    with (data/'sparse/0/images.txt').open('a') as f:f.write(' '.join(row)+'\n\n')
    base=json.loads(fit_plan.read_text());fit=base['command'].copy();source=Path(fit[fit.index('--init-ply')+1])
    prior=json.loads((fit_plan.parent/'plan.json').read_text())
    if group.sha(source)!=prior['source_ply_sha256'] or group.sha(fit[0])!=prior['binary_sha256']:raise ValueError('Starting PLY or trainer hash mismatch')
    for key,value in [('--data',str(data)),('--output-dir-prefix',str(output)),('--output-dir-name','fit'),('--steps-per-save','0')]:fit[fit.index(key)+1]=value
    zero=fit.copy();zero[zero.index('--output-dir-name')+1]='zero';zero[zero.index('--num-iterations')+1]='0'
    result={'description':'Original 1500 cam0 is the sole fitting image and duplicated for evaluation; 1495 and 1505 of each physical lens are evaluation only. All were original training captures, not heldouts. Original poses, source pixels, masks and 7k PLY; no appearance or image alignment.','staging':evidence,'eval_order':sorted([dup,*['eval_'+n[6:] for n in neighbors]]),'zero_command':zero,'fit_command':fit,'source_ply_sha256':group.sha(source),'binary_sha256':group.sha(fit[0]),'previous_fit_plan_sha256':group.sha(fit_plan),'staged_pose_sha256':group.sha(data/'sparse/0/images.txt'),'incremental_output_limit_bytes':30000000,'combined_gpu_timeout_seconds':180}
    (output/'crossview-plan.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'eval_order':result['eval_order'],'zero_command':zero,'fit_command':fit},indent=2))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('manifest');p.add_argument('fit_plan');p.add_argument('output');a=p.parse_args();stage(a.manifest,a.fit_plan,a.output)
if __name__=='__main__':main()
