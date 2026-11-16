#!/usr/bin/env python3
"""Run a staged zero-update pose sweep with storage and time limits."""
import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

FREE_RESERVE = 35 * 1024**3
TOTAL_LIMIT = 15_000_000_000
SUPPORT_LIMIT = 2_000_000_000
OUTPUT_LIMIT = 15_000_000


def inventory(script):
    return json.loads(subprocess.run(['python3',str(script)],check=True,capture_output=True,text=True).stdout)


def output_size(path):
    return sum(f.stat().st_size for f in path.rglob('*') if f.is_file()) if path.exists() else 0


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('staged',type=Path);p.add_argument('reference_config',type=Path);p.add_argument('--inventory-script',type=Path,required=True,help='Storage inventory script returning total_kib and totals_kib.support JSON');a=p.parse_args();staged=a.staged.resolve(strict=True);reference=a.reference_config.resolve(strict=True);plan=json.loads((staged/'plan.json').read_text());cmd=plan['command'];out=staged/'render'
    if out.exists():raise FileExistsError(out)
    stat=inventory(a.inventory_script)
    if stat['total_kib']*1024+OUTPUT_LIMIT>=TOTAL_LIMIT or stat['totals_kib']['support']*1024>=SUPPORT_LIMIT or shutil.disk_usage(staged).free<FREE_RESERVE:raise ValueError('Insufficient task, support or free-space budget')
    ref=json.loads(reference.read_text());reason=None;checked=False;peak=0;start=time.monotonic();last=0
    with (staged/'render.log').open('x') as log:
      proc=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,env=dict(os.environ,SS_LANG='en'))
      while proc.poll() is None:
        time.sleep(.25);size=output_size(out)+(staged/'render.log').stat().st_size;peak=max(peak,size)
        if size>OUTPUT_LIMIT or shutil.disk_usage(staged).free<FREE_RESERVE:reason='output or free-space limit';break
        if time.monotonic()-start>180:reason='180-second limit';break
        config=out/'config.json'
        if config.exists() and not checked:
            try:current=json.loads(config.read_text())
            except json.JSONDecodeError:current=None
            if current is not None:
                diff={k:[ref.get(k),current.get(k)] for k in set(ref)|set(current) if ref.get(k)!=current.get(k)}
                allowed={'data','output_dir_prefix','output_dir_name','steps_per_save','save_eval_images'}
                if set(diff)-allowed or current.get('num_iterations')!=0 or current.get('steps_per_save')!=0 or current.get('save_eval_images') is not False:reason='resolved configuration mismatch';break
                (staged/'config-diff.json').write_text(json.dumps(diff,indent=2)+'\n');checked=True
        if time.monotonic()-last>3:
            stat=inventory(a.inventory_script);last=time.monotonic()
            if stat['total_kib']*1024>=TOTAL_LIMIT or stat['totals_kib']['support']*1024>=SUPPORT_LIMIT:reason='task or support limit';break
      if reason:
        try:os.killpg(proc.pid,signal.SIGKILL)
        except (ProcessLookupError,PermissionError):pass
      code=proc.wait()
    size=output_size(out)+(staged/'render.log').stat().st_size;peak=max(peak,size);stat=inventory(a.inventory_script)
    if size>OUTPUT_LIMIT or stat['total_kib']*1024>=TOTAL_LIMIT or stat['totals_kib']['support']*1024>=SUPPORT_LIMIT or shutil.disk_usage(staged).free<FREE_RESERVE:reason=reason or 'final storage limit'
    if not checked:reason=reason or 'resolved configuration not verified'
    status={'exit_code':code,'reason':reason,'elapsed_seconds':time.monotonic()-start,'observed_peak_bytes':peak,'inventory':stat}
    (staged/'status.json').write_text(json.dumps(status,indent=2)+'\n');print(json.dumps(status,indent=2))
    if reason or code:raise SystemExit(1)
if __name__=='__main__':main()
