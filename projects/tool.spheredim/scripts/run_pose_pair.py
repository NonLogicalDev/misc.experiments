#!/usr/bin/env python3
"""Run a reviewed no-warp comparison, stopping before disk limits are crossed."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import threading
import time

RESERVE=35*1024**3
LIMIT=2*1024**3


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def tree_size(root):
    return sum(p.stat().st_size for p in root.rglob('*') if p.is_file() and not p.is_symlink()) if root.exists() else 0


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('manifest',type=Path);a=p.parse_args();manifest=a.manifest.resolve(strict=True);pair=json.loads(manifest.read_text());parent=manifest.parent
    log=parent/'pose-ab-no-warp.log';status=parent/'pose-ab-no-warp.status.json';outputs=[parent/'pose-ab-unfiltered-no-warp',parent/'pose-ab-exclude-three-no-warp']
    if any(x.exists() for x in [log,status,*outputs]):p.error('A pair output, log or status already exists')
    base=Path(pair['baseline_dataset']);excluded=Path(pair['exclusion_dataset']);commands=pair['commands']
    if sha(base/'manifest.json')!=pair['baseline_manifest_sha256'] or sha(excluded/'manifest.json')!=pair['exclusion_manifest_sha256'] or sha(base/'seed.ply')!=pair['seed_sha256'] or sha(Path(commands['baseline'][0]))!=pair['executable_sha256']:p.error('Inputs or executable differ from reviewed manifest')
    for key,expected in (('baseline',base),('exclude_three',excluded)):
        cmd=commands[key]
        if cmd[cmd.index('--data')+1]!=str(expected) or cmd[cmd.index('--output-dir-prefix')+1]!=str(parent):p.error('Invalid command paths')
        for flag,value in (('--calib-correction','off'),('--use-calib-warp','0'),('--perceptual-loss','ssim'),('--eval-align','0'),('--num-iterations','3000')):
            if cmd[cmd.index(flag)+1]!=value:p.error(f'Invalid reviewed option {flag}')
    if shutil.disk_usage(parent).free<RESERVE+LIMIT:p.error('Less than 35 GiB reserve plus 2 GiB budget remains')
    started=time.monotonic();state={'stage':'Preparing comparison','status':'starting','current':0,'total':3000,'elapsed_seconds':0,'output_bytes':0,'free_bytes':shutil.disk_usage(parent).free,'error':None,'camera_count':None,'cameras_after_splitting':None,'completed_arms':[],'manifest':str(manifest)}
    def save():
        tmp=status.with_suffix('.tmp');tmp.write_text(json.dumps(state,indent=2)+'\n');os.replace(tmp,status)
    def budget():
        state['elapsed_seconds']=time.monotonic()-started;state['output_bytes']=sum(map(tree_size,outputs))+(log.stat().st_size if log.exists() else 0);state['free_bytes']=shutil.disk_usage(parent).free
        if state['free_bytes']<RESERVE:return 'Free space below 35 GiB reserve'
        if state['output_bytes']>LIMIT:return 'Pair output exceeded 2 GiB limit'
        return None
    save();proc=None
    try:
        with log.open('x',buffering=1) as logfile:
            for key,count in (('baseline',116),('exclude_three',113)):
                problem=budget()
                if problem:raise RuntimeError(problem)
                cmd=commands[key];state.update(stage='Baseline: Gaussian training' if key=='baseline' else 'Exclusion: Gaussian training',status='running',current=0,camera_count=None,cameras_after_splitting=None);save()
                logfile.write('\nCOMMAND '+json.dumps(cmd)+'\n');proc=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1,env=dict(os.environ,SS_LANG='en'));q=queue.Queue()
                def read_lines():
                    for line in proc.stdout:q.put(line)
                    q.put(None)
                threading.Thread(target=read_lines,daemon=True).start();last=0;done=False;seen=False
                while not done:
                    try:line=q.get(timeout=1)
                    except queue.Empty:line=''
                    if line is None:done=True
                    elif line:
                        logfile.write(line)
                        m=re.search(r'Cameras:\s*(\d+)\s*\((\d+) after splitting\)',line)
                        if m:
                            seen=True;state.update(camera_count=int(m[1]),cameras_after_splitting=int(m[2]))
                            if (int(m[1]),int(m[2]))!=(count,count):state['error']='Unexpected camera count or split';proc.terminate()
                        m=re.search(r'step\s+(\d+)\s*/\s*(\d+).*?splats\s+(\d+)',line)
                        if m:state.update(current=int(m[1]),splats=int(m[3]))
                    now=time.monotonic()
                    if now-last>=5 or done:
                        problem=budget();last=now
                        if problem:
                            state['error']=problem
                            if proc.poll() is None:proc.terminate()
                        save()
                code=proc.wait();budget()
                if state['error'] or code or not seen or state['current']!=3000:raise RuntimeError(state['error'] or f'{key}: exit={code}, seen={seen}, step={state["current"]}')
                out=outputs[0 if key=='baseline' else 1];cfg=json.loads((out/'config.json').read_text())
                if cfg['use_calib_warp'] or cfg['perceptual_loss']!='ssim' or cfg['eval_mode']!='interval' or cfg['eval_interval']!=8 or cfg['sampling_seed']!=42:raise RuntimeError('Saved configuration does not match the reviewed settings')
                metrics=json.loads((out/'metrics.json').read_text())
                if metrics['num_eval_images']!=17:raise RuntimeError('Unexpected evaluation image count')
                state['completed_arms'].append({'arm':key,'checkpoint_sha256':sha(out/'step-000003000.ckpt/splat.ply'),'metrics_sha256':sha(out/'metrics.json'),'eval_images':17});save()
            state.update(status='complete',stage='Training complete; comparison pending',current=3000);budget();save()
    except BaseException as e:
        if proc and proc.poll() is None:proc.terminate();proc.wait()
        state.update(status='failed',error=f'{type(e).__name__}: {e}');budget();save();raise
if __name__=='__main__':main()
