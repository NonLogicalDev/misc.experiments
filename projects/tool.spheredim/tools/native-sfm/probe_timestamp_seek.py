#!/usr/bin/env python3
"""Compare timestamp-seeking physical-lens exports with preserved index exports."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True);p.add_argument('--baseline-probe',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--frames',type=int,nargs='+',required=True);p.add_argument('--worker',action='store_true');p.add_argument('--timestamps',type=float,nargs='+');a=p.parse_args()
    if a.worker:
        import insta360_rs as ins
        c=ins.StitchConfig(backend=ins.ProcessingBackend.GPU,stabilization=ins.Stabilization.OFF,rolling_shutter=ins.RollingShutterCorrection.OFF,seam_mode=ins.SeamMode.FIXED,width=2048,height=1024)
        r=ins.start_export_frames(str(a.source),str(a.output),timestamps=a.timestamps,config=c,format=ins.ImageFormat.PNG).wait()
        print(json.dumps({'backend':str(r.backend.selected),'outputs':[str(x) for x in r.outputs]}));return
    if a.output.exists():raise FileExistsError(a.output)
    baseline=json.loads(a.baseline_probe.read_text());byframe={r['frame']:r for r in baseline['frames']}
    if len(set(a.frames))!=len(a.frames) or any(n not in byframe for n in a.frames):raise ValueError('Need unique baseline frames')
    if shutil.disk_usage(a.output.parent).free<35*1024**3+100*1024**2:raise RuntimeError('Insufficient reserve')
    a.output.mkdir();(a.output/'INCOMPLETE').write_text('Incomplete timestamp pilot\n');started=time.monotonic();report=[]
    for mode in ('lens0','lens1','mask0','mask1'):
        env=os.environ.copy();env['SPHEREDIM_OBSERVATION_MODE']=mode;env.pop('SPHEREDIM_LENS1_INVERSE_QUAT_WXYZ',None)
        times=[byframe[n]['timestamp_microseconds']/1e6 for n in a.frames];out=a.output/mode
        cmd=[sys.executable,str(Path(__file__).resolve()),'--worker','--source',str(a.source),'--baseline-probe',str(a.baseline_probe),'--output',str(out),'--frames',*map(str,a.frames),'--timestamps',*map(str,times)]
        with (a.output/f'{mode}.log').open('w') as log:
            proc=subprocess.Popen(cmd,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True);deadline=started+80
            try:
                while proc.poll() is None:
                    size=sum(f.stat().st_size for f in a.output.rglob('*') if f.is_file())
                    if size>100*1024**2 or shutil.disk_usage(a.output).free<35*1024**3 or time.monotonic()>deadline:raise RuntimeError('Budget, reserve or time limit reached')
                    time.sleep(.5)
            except BaseException:
                os.killpg(proc.pid,signal.SIGTERM)
                try:proc.wait(timeout=5)
                except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait(timeout=5)
                raise
        if proc.returncode:raise RuntimeError(f'{mode} failed; see log')
        text=(a.output/f'{mode}.log').read_text(); observed=[(int(k),int(t)) for k,t in re.findall(r'SPHEREDIM_FRAME (\d+) (-?\d+)',text)]
        expected=[(byframe[n]['timestamp_microseconds'],byframe[n]['timestamp_microseconds']) for n in a.frames]
        if observed!=expected:raise ValueError(f'{mode} emitted unexpected timestamps: {observed} != {expected}')
        for n in a.frames:
            t=byframe[n]['timestamp_microseconds'];path=out/f'frame_{t:016d}.png';actual=sha(path);expected_sha=byframe[n][mode+'_sha256']
            report.append({'mode':mode,'source_frame':n,'timestamp_microseconds':t,'sha256':actual,'baseline_sha256':expected_sha,'matches':actual==expected_sha})
    result={'status':'completed comparison; not a production export','elapsed_seconds':time.monotonic()-started,'source_sha256':sha(a.source),'baseline_probe_sha256':sha(a.baseline_probe),'results':report}
    (a.output/'result.json').write_text(json.dumps(result,indent=2)+'\n');(a.output/'INCOMPLETE').unlink();print(json.dumps(result,indent=2))


if __name__=='__main__':main()
