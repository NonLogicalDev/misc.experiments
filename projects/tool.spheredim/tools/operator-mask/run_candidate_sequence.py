#!/usr/bin/env python3
"""Prepare bounded SAM candidates and contact sheets for a full ERP sequence."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(4 * 1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def size(root):
    return sum(p.stat().st_size for p in root.rglob('*') if p.is_file())


def run(cmd, root, env, budget, reserve, log):
    with (root / log).open('w') as handle:
        proc = subprocess.Popen(cmd, stdout=handle, stderr=subprocess.STDOUT, env=env, start_new_session=True)
        try:
            while proc.poll() is None:
                if size(root) > budget or shutil.disk_usage(root).free < reserve:
                    raise RuntimeError('Output budget or free-space reserve exceeded')
                time.sleep(1)
        except BaseException:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait()
            raise
    if proc.returncode:
        raise RuntimeError(f'{cmd[0]} exited {proc.returncode}; see {log}')
    if size(root) > budget or shutil.disk_usage(root).free < reserve:
        raise RuntimeError('Output budget or free-space reserve exceeded')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('off-video', 'stable-video', 'fused-csv', 'model', 'spirula', 'output'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--config-dir', type=Path, required=True, help='existing Spirula config with license acceptance')
    p.add_argument('--count', type=int, required=True)
    p.add_argument('--stride', type=int, required=True)
    p.add_argument('--budget-mib', type=int, required=True)
    p.add_argument('--reserve-gib', type=int, required=True)
    args = p.parse_args()
    if min(args.count,args.stride,args.budget_mib,args.reserve_gib) <= 0:
        p.error('count, stride, budget and reserve must be positive')
    root = args.output
    root.mkdir(parents=True, exist_ok=False)
    (root / 'INCOMPLETE').write_text('Candidate generation has not completed.\n')
    env = os.environ.copy()
    env['XDG_CONFIG_HOME'] = str(args.config_dir.resolve())
    budget = args.budget_mib * 1024**2
    reserve = args.reserve_gib * 1024**3
    if shutil.disk_usage(root).free < reserve:
        raise RuntimeError('Free space is below the requested reserve')
    project = Path(__file__).resolve().parents[2]
    lock = project / 'vendor/360DVO/requirements-macos-arm64-py314.lock'
    uv = ['uv', 'run', '--offline', '--isolated', '--no-project', '--python', '3.14', '--with-requirements', str(lock), 'python']
    last = (args.count - 1) * args.stride
    with args.fused_csv.open(newline='') as handle:
        orientation = list(csv.DictReader(handle))
    if last >= len(orientation):
        raise ValueError('Requested source frames exceed orientation CSV')
    for video in (args.off_video, args.stable_video):
        probe = subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-show_entries','frame=best_effort_timestamp_time','-of','json',str(video)])
        timestamps = json.loads(probe)['frames']
        for n in range(0, last + 1, args.stride):
            if n >= len(timestamps) or int(orientation[n]['frame']) != n or abs(float(timestamps[n]['best_effort_timestamp_time']) - float(orientation[n]['video_pts_s'])) > 1e-5:
                raise ValueError(f'Video and orientation timestamp mismatch at {video} frame {n}')
    inputs = [args.off_video, args.stable_video, args.fused_csv, args.model, args.spirula]
    provenance = {'status':'unreviewed candidates', 'sources': {str(f.resolve()):sha(f) for f in inputs}, 'count':args.count, 'stride':args.stride, 'last_frame':last, 'budget_mib':args.budget_mib, 'reserve_gib':args.reserve_gib, 'sam_points':[[450,45],[510,135]], 'dilate_ratio':.15, 'source_guard':4, 'output_guard':32}
    (root / 'provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
    for label, video in [('off', args.off_video), ('stable', args.stable_video)]:
        directory = root / label
        directory.mkdir()
        cmd = ['ffmpeg','-hide_banner','-loglevel','error','-i',str(video),'-vf',f'select=not(mod(n\\,{args.stride}))*lte(n\\,{last}),scale=1024:512','-fps_mode','passthrough','-frames:v',str(args.count),'-start_number','0',str(directory/'frame_%05d.png')]
        run(cmd,root,env,budget,reserve,f'{label}.log')
        if len(list(directory.glob('frame_*.png'))) != args.count:
            raise RuntimeError(f'{label} frame count mismatch')
    run([str(args.spirula),'sam','track','--model',str(args.model),'--frames',str(root/'off'),'--point','450,45','--point','510,135','--dilate-ratio','0.15','--max-frames',str(args.count),'--out',str(root/'sam')],root,env,budget,reserve,'sam.log')
    run(uv+[str(project/'tools/operator-mask/warp_sequence.py'),str(root/'sam'),str(args.fused_csv),str(root/'warped'),'--first-frame','0','--stride',str(args.stride),'--guard','4','--output-guard','32'],root,env,budget,reserve,'warp.log')
    run(uv+[str(project/'tools/operator-mask/review_candidates.py'),str(root/'warped/manifest.json'),str(root/'stable'),str(root/'review'),'--max-frames',str(args.count)],root,env,budget,reserve,'review.log')
    (root/'INCOMPLETE').unlink()
    print('Unreviewed candidates prepared:',root)


if __name__ == '__main__':
    main()
