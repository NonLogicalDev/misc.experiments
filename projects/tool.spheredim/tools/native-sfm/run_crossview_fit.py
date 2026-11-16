#!/usr/bin/env python3
"""Run the two staged cross-view diagnostics with bounded storage and time."""
import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time
import cv2
import numpy as np
import prepare_capture_group as group

def inventory(path):return json.loads(subprocess.run(['python3',str(path)],capture_output=True,text=True,check=True).stdout)
def new_bytes(path):
    return sum(f.stat().st_size for f in path.rglob('*') if f.is_file() and f.stat().st_nlink==1)

def deduplicate_references(root,run,order):
    result=[]
    for i,name in enumerate(order):
        for prefix,folder,mode in [('eval-gt','images',cv2.IMREAD_COLOR),('eval-mask','masks',cv2.IMREAD_GRAYSCALE)]:
            target=run/f'{prefix}-{i:05d}.png';source=root/'data'/folder/name
            a=cv2.imread(str(target),mode);b=cv2.imread(str(source),mode)
            if a is None or b is None or not np.array_equal(a,b):raise ValueError(f'Saved reference differs from source pixels: {target}')
            before=group.sha(target);temp=target.with_name(target.name+'.link');os.link(source,temp);os.replace(temp,target)
            result.append({'path':str(target),'saved_png_sha256':before,'source_png_sha256':group.sha(source),'decoded_pixels_identical':True})
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('staged',type=Path);p.add_argument('previous_config',type=Path);p.add_argument('--inventory',type=Path,required=True,help='Existing task storage inventory script');a=p.parse_args();root=a.staged.resolve(strict=True);plan=json.loads((root/'crossview-plan.json').read_text());previous=json.loads(a.previous_config.read_text());inv=inventory(a.inventory)
    if inv['total_kib']*1024+30000000>=15000000000 or inv['totals_kib']['support']*1024>=2000000000 or shutil.disk_usage(root).free<35*1024**3:raise ValueError('Insufficient storage')
    start=time.monotonic();result={'runs':{},'reference_hardlinks':{}}
    for name in ('zero','fit'):
        out=root/name
        if out.exists():raise FileExistsError(out)
        reason=None;checked=False;last=0;peak=0
        with (root/f'{name}.log').open('x') as log:
            proc=subprocess.Popen(plan[f'{name}_command'],stdout=log,stderr=subprocess.STDOUT,start_new_session=True,env=dict(os.environ,SS_LANG='en'))
            while proc.poll() is None:
                time.sleep(.25);size=new_bytes(root);peak=max(peak,size)
                if size>30000000 or shutil.disk_usage(root).free<35*1024**3:reason='output or free-space limit';break
                if time.monotonic()-start>180:reason='combined 180-second limit';break
                path=out/'config.json'
                if path.exists() and not checked:
                    try:config=json.loads(path.read_text())
                    except json.JSONDecodeError:config=None
                    if config is not None:
                        diff={k:[previous.get(k),config.get(k)] for k in set(previous)|set(config) if previous.get(k)!=config.get(k)}
                        allowed={'data','output_dir_prefix','output_dir_name','steps_per_save','num_iterations'}
                        if set(diff)-allowed or config.get('steps_per_save')!=0 or config.get('num_iterations')!=(0 if name=='zero' else 500):reason='configuration mismatch';break
                        (root/f'{name}-config-diff.json').write_text(json.dumps(diff,indent=2)+'\n');checked=True
                if time.monotonic()-last>3:
                    inv=inventory(a.inventory);last=time.monotonic()
                    if inv['total_kib']*1024>=15000000000 or inv['totals_kib']['support']*1024>=2000000000:reason='task or support limit';break
            if reason:
                try:os.killpg(proc.pid,signal.SIGKILL)
                except (ProcessLookupError,PermissionError):pass
            code=proc.wait()
        inv=inventory(a.inventory);peak=max(peak,new_bytes(root))
        if new_bytes(root)>30000000 or inv['total_kib']*1024>=15000000000 or inv['totals_kib']['support']*1024>=2000000000 or shutil.disk_usage(root).free<35*1024**3:reason=reason or 'final storage limit'
        if not checked:reason=reason or 'configuration not verified'
        result['runs'][name]={'exit_code':code,'reason':reason,'peak_incremental_bytes':peak,'combined_elapsed_seconds':time.monotonic()-start}
        if reason or code:
            (root/'status.json').write_text(json.dumps(result,indent=2)+'\n');raise SystemExit(1)
        result['reference_hardlinks'][name]=deduplicate_references(root,out,plan['eval_order'])
        (root/'status.json').write_text(json.dumps(result,indent=2)+'\n')
    result['final_new_bytes']=new_bytes(root);result['inventory']=inventory(a.inventory);(root/'status.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'runs':result['runs'],'final_new_bytes':result['final_new_bytes']},indent=2))
if __name__=='__main__':main()
