#!/usr/bin/env python3
"""Render original training cameras with a guarded zero-step raw checkpoint resume."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tarfile
import time

import cv2
import numpy as np
import evaluate_splat as ev

RESERVE = 35 * 1024**3
LIMIT = 250 * 1024**2


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def load(path, gray=False):
    result = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE if gray else cv2.IMREAD_COLOR)
    if result is None:
        raise ValueError(f'Cannot read {path}')
    return result


def prepare(source, original_run, output, frames):
    source, original_run = (Path(x).resolve(strict=True) for x in (source, original_run))
    output = Path(output).resolve()
    if output.exists() or shutil.disk_usage(output.parent).free < RESERVE + LIMIT:
        raise ValueError('Output exists or 35 GiB reserve plus 250 MiB budget unavailable')
    manifest = json.loads((source / 'manifest.json').read_text())
    config = json.loads((original_run / 'config.json').read_text())
    step = config['num_iterations']
    if not isinstance(step, int) or isinstance(step, bool) or step < 1:
        raise ValueError('Invalid original iteration count')
    ckpt = original_run / f'step-{step:09d}.ckpt'
    with tarfile.open(ckpt / 'state.tar') as archive:
        state = json.load(archive.extractfile('state.json'))
    if state['step'] != step or state['full_resume'] != 1:
        raise ValueError('Expected resumable checkpoint at the original final step')
    if config['mask_boundary_offset'] != 0 or config['warp_to_pinhole'] or config['warp_spherical_to_pinhole'] or config['use_calib_warp']:
        raise ValueError('Original settings do not match this audited raw ERP path')
    names = {x['name'] for x in manifest['frames']}
    selected = [f'train_{frame:06d}_cam{lens}.png' for frame in frames for lens in (0, 1)]
    if not selected or len(selected) != len(set(selected)) or not set(selected) <= names:
        raise ValueError('Selected timestamps must be distinct original paired training cameras')
    heldouts = manifest['heldout_evaluation_order']
    if heldouts != sorted(heldouts) or len(heldouts) <= len(selected):
        raise ValueError('Not enough ordered held-out cameras to preserve train count')
    swaps = heldouts[:len(selected)]
    rename = {name: name.replace('train_', 'eval_', 1) for name in selected}
    rename.update({name: name.replace('eval_', 'train_', 1) for name in swaps})
    if set(rename.values()) & (names - set(rename)):
        raise ValueError('Renamed files collide')
    binary = Path(manifest['command'][0]).resolve(strict=True)
    if sha(binary) != manifest['binary_sha256']:
        raise ValueError('Trainer binary differs from original')
    output.mkdir(); (output / 'INCOMPLETE').write_text('Audit has not completed\n')
    data = output / 'data'; (data / 'sparse/0').mkdir(parents=True)
    for folder in ('images', 'masks'):
        (data / folder).mkdir()
        for name in sorted(names):
            os.link(source / folder / name, data / folder / rename.get(name, name))
    for name in ('cameras.txt', 'points3D.txt'):
        os.link(source / 'sparse/0' / name, data / 'sparse/0' / name)
    os.link(source / 'seed.ply', data / 'seed.ply')
    lines = (source / 'sparse/0/images.txt').read_text().splitlines(keepends=True)
    if len(lines) != 2 * len(names):
        raise ValueError('Unexpected source image rows')
    seen = set()
    for i in range(0, len(lines), 2):
        fields = lines[i].split(); old = fields[-1]; seen.add(old)
        fields[-1] = rename.get(old, old); lines[i] = ' '.join(fields) + '\n'
    if seen != names:
        raise ValueError('Source pose names do not match manifest')
    (data / 'sparse/0/images.txt').write_text(''.join(lines))
    cmd = [str(binary), 'train', '360-camera', '--resume', str(ckpt), '--data', str(data),
           '--output-dir-prefix', str(output), '--output-dir-name', 'render',
           '--num-iterations', str(step), '--steps-per-save', '0', '--disable-viewer', '1',
           '--save-eval-images', '1', '--eval-lpips', '0', '--eval-align', '0',
           '--mask-boundary-offset', '0', '--warp-to-pinhole', '0']
    plan = {'method': 'Raw eval forward, not camera-indexed appearance or training loss.',
            'source': str(source), 'original_run': str(original_run), 'checkpoint': str(ckpt),
            'source_manifest_sha256': sha(source / 'manifest.json'), 'binary_sha256': sha(binary),
            'checkpoint_state_sha256': sha(ckpt / 'state.tar'), 'checkpoint_ply_sha256': sha(ckpt / 'splat.ply'),
            'checkpoint_step': step, 'original_pose_sha256': sha(source / 'sparse/0/images.txt'),
            'audit_pose_sha256': sha(data / 'sparse/0/images.txt'), 'rename': rename,
            'original_eval_order': heldouts, 'command': cmd}
    (output / 'plan.json').write_text(json.dumps(plan, indent=2) + '\n')
    return plan


def run(output, plan):
    render = output / 'render'; log = output / 'run.log'
    if render.exists() or log.exists():
        raise FileExistsError('Run output exists')
    started = time.monotonic()
    with log.open('xb') as f:
        proc = subprocess.Popen(plan['command'], stdout=f, stderr=subprocess.STDOUT,
                                start_new_session=True, env=dict(os.environ, SS_LANG='en'))
        try:
            while proc.poll() is None:
                size = sum(p.stat().st_size for p in render.rglob('*') if p.is_file()) if render.exists() else 0
                if shutil.disk_usage(output).free < RESERVE or size > LIMIT or time.monotonic() - started > 600:
                    os.killpg(proc.pid, signal.SIGTERM); proc.wait(timeout=10)
                    raise RuntimeError('Audit exceeded time, output or free-space limit')
                time.sleep(1)
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL); proc.wait()
    if proc.returncode:
        raise RuntimeError(f'Render failed: exit {proc.returncode}')
    return time.monotonic() - started


def evaluate(output, plan, elapsed):
    source = Path(plan['source']); original = Path(plan['original_run']); run = output / 'render'
    log = (output / 'run.log').read_text(errors='replace')
    if f"at step {plan['checkpoint_step']}" not in log or 'Eval: views to score:' not in log or list(run.glob('step-*.ckpt')):
        raise ValueError('Resume/evaluation evidence missing or checkpoint written')
    # CLI applies its named preset again on resume: verify every resolved setting.
    old_config = json.loads((original / 'config.json').read_text()); new_config = json.loads((run / 'config.json').read_text())
    diff = {k: [old_config.get(k), new_config.get(k)] for k in set(old_config) | set(new_config) if old_config.get(k) != new_config.get(k)}
    if set(diff) - {'data', 'output_dir_prefix', 'output_dir_name', 'resume', 'steps_per_save'}:
        raise ValueError(f'Unexpected resolved config differences: {diff}')
    ckpt = Path(plan['checkpoint'])
    if sha(ckpt / 'state.tar') != plan['checkpoint_state_sha256'] or sha(ckpt / 'splat.ply') != plan['checkpoint_ply_sha256']:
        raise ValueError('Original checkpoint changed')
    new = sorted(p.name for p in (output / 'data/images').iterdir() if p.name.startswith('eval_'))
    old = plan['original_eval_order']; controls = sorted(set(old) & set(new))
    if len(new) != len(old) or len(controls) != len(old) - len(plan['rename']) // 2:
        raise ValueError('Evaluation split differs from plan')
    for name in controls:
        for kind in ('gt', 'mask', 'render'):
            a = load(original / f'eval-{kind}-{old.index(name):05d}.png')
            b = load(run / f'eval-{kind}-{new.index(name):05d}.png')
            if not np.array_equal(a, b):
                raise ValueError(f'Control differs: {name} {kind}')
    pose_lines = (source / 'sparse/0/images.txt').read_text().splitlines()[::2]
    poses = {line.split()[-1]: line.split()[:-1] for line in pose_lines}
    rows = []; tiles = []
    for original_name, target in plan['rename'].items():
        if not original_name.startswith('train_'):
            continue
        i = new.index(target); refpath = source / 'images' / original_name; maskpath = source / 'masks' / original_name
        ref, mask = load(refpath), load(maskpath, True)
        gt = load(run / f'eval-gt-{i:05d}.png'); predpath = run / f'eval-render-{i:05d}.png'; pred = load(predpath)
        mask_saved = load(run / f'eval-mask-{i:05d}.png', True)
        if not np.array_equal(mask, mask_saved) or np.abs(ref.astype(np.int16)-gt.astype(np.int16)).max() > 1:
            raise ValueError(f'Training reference or mask differs: {original_name}')
        metric = ev.metrics.frame_metrics(ref, pred, mask); metric['spherical_ssim'] = ev.spherical_ssim(ref, pred, mask)
        rows.append({'name': original_name, 'index': i, 'colmap_pose_row': poses[original_name], 'source_sha256': sha(refpath), 'mask_sha256': sha(maskpath), 'render_sha256': sha(predpath), 'metrics': metric})
        tile = np.concatenate((ref, pred), axis=1); cv2.rectangle(tile, (0, 0), (2047, 27), (0, 0, 0), -1)
        cv2.putText(tile, original_name + '  source left / raw render right', (8, 19), cv2.FONT_HERSHEY_SIMPLEX, .55, (255, 255, 255), 1, cv2.LINE_AA); tiles.append(tile)
    report = {'method': 'Original training poses, raw eval forward; appearance correction excluded. No alignment. Controls are prior held-out images.',
              'control_count_exact': len(controls), 'config_differences': diff, 'elapsed_seconds': elapsed,
              'plan_sha256': sha(output / 'plan.json'), 'run_log_sha256': sha(output / 'run.log'),
              'checkpoint_state_sha256': plan['checkpoint_state_sha256'], 'checkpoint_ply_sha256': plan['checkpoint_ply_sha256'], 'frames': rows}
    (output / 'audit.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    if not cv2.imwrite(str(output / 'sheet.png'), np.concatenate(tiles, axis=0)):
        raise RuntimeError('Could not write contact sheet')
    (output / 'INCOMPLETE').unlink()
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source', type=Path); p.add_argument('original_run', type=Path); p.add_argument('output', type=Path)
    p.add_argument('--frames', type=int, nargs='+', required=True)
    a = p.parse_args(); plan = prepare(a.source, a.original_run, a.output, a.frames)
    elapsed = run(a.output, plan); report = evaluate(a.output, plan, elapsed)
    print(json.dumps({'controls': report['control_count_exact'], 'elapsed_seconds': elapsed, 'frames': len(report['frames'])}))


if __name__ == '__main__':
    main()
