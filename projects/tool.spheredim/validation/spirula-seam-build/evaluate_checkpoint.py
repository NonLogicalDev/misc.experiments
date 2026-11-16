"""Compare two renderers at held-out and selected training camera positions."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/native-sfm'))
import compare_splat_pixels as pixels
import numpy as np

RESERVE = 35 * 1024**3
LIMIT = 250 * 1024**2


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def tree_size(root):
    return sum(p.stat().st_size for p in root.rglob('*') if p.is_file() and not p.is_symlink())


def run(command, output, log):
    with log.open('xb') as f:
        proc = subprocess.Popen(command, stdout=f, stderr=subprocess.STDOUT, start_new_session=True, env=dict(os.environ, SS_LANG='en'))
        start = time.monotonic()
        try:
            while proc.poll() is None:
                if tree_size(output) > LIMIT or shutil.disk_usage(output).free < RESERVE or time.monotonic() - start > 600:
                    os.killpg(proc.pid, signal.SIGTERM); proc.wait(timeout=10)
                    raise RuntimeError('Evaluation exceeded output, free-space or time limit')
                time.sleep(1)
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                try: proc.wait(timeout=10)
                except subprocess.TimeoutExpired: os.killpg(proc.pid, signal.SIGKILL); proc.wait()
    if tree_size(output) > LIMIT or shutil.disk_usage(output).free < RESERVE: raise RuntimeError('Evaluation exceeded output or free-space limit')
    if proc.returncode: raise RuntimeError(f'Evaluation failed: {proc.returncode}')
    return time.monotonic() - start


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('checkpoint_run', type=Path)
    parser.add_argument('audit_dir', type=Path, help='Existing selected-training-view audit directory')
    parser.add_argument('baseline', type=Path)
    parser.add_argument('candidate', type=Path)
    parser.add_argument('output', type=Path, help='New output directory')
    a = parser.parse_args()
    checkpoint_run, audit, baseline, candidate = [p.resolve(strict=True) for p in (a.checkpoint_run, a.audit_dir, a.baseline, a.candidate)]
    output = a.output.resolve()
    if output.exists() or not output.parent.is_dir(): parser.error('Output must be new in an existing directory')
    if shutil.disk_usage(output.parent).free < RESERVE + LIMIT: parser.error('Need 35 GiB reserve plus 250 MiB budget')
    config = json.loads((checkpoint_run / 'config.json').read_text()); step = config['num_iterations']
    if step != 6000: parser.error('Expected the selected 6000-step checkpoint')
    checkpoint = checkpoint_run / f'step-{step:09d}.ckpt'
    input_paths = [checkpoint_run / 'config.json', checkpoint / 'splat.ply', checkpoint / 'state.tar']
    hashes = {str(p): sha(p) for p in input_paths}
    binary_hashes = {str(p): sha(p) for p in (baseline, candidate)}
    if len(set(binary_hashes.values())) != 2: parser.error('Renderer binaries are identical')
    original_data = Path(config['data']).resolve(strict=True); audit_data = (audit / 'data').resolve(strict=True)
    manifest = json.loads((original_data / 'manifest.json').read_text())
    plan = json.loads((audit / 'plan.json').read_text())
    if Path(plan['source']).resolve() != original_data or Path(plan['checkpoint']).resolve() != checkpoint.resolve(): parser.error('Training-view audit does not match checkpoint and dataset')
    expected = {'source_manifest_sha256': original_data / 'manifest.json', 'checkpoint_state_sha256': checkpoint / 'state.tar', 'checkpoint_ply_sha256': checkpoint / 'splat.ply', 'original_pose_sha256': original_data / 'sparse/0/images.txt', 'audit_pose_sha256': audit_data / 'sparse/0/images.txt'}
    if any(sha(path) != plan[key] for key, path in expected.items()): parser.error('Audit provenance hash mismatch')
    for old, new in plan['rename'].items():
        for folder in ('images', 'masks'):
            if sha(original_data / folder / old) != sha(audit_data / folder / new): parser.error('Audit image or mask mismatch')
    selected = {new for old, new in plan['rename'].items() if old.startswith('train_')}
    if len(selected) != 10: parser.error('Expected 10 selected training views')
    output.mkdir(); report = {'checkpoint_hashes': hashes, 'binary_hashes': binary_hashes, 'audit_plan_sha256': sha(audit / 'plan.json'), 'runs': {}, 'comparisons': {}}
    for subset, data in [('heldout', original_data), ('training', audit_data)]:
        names = sorted(p.name for p in (data / 'images').iterdir() if p.name.startswith('eval_'))
        if len(names) != 36 or (subset == 'heldout' and names != manifest['heldout_evaluation_order']) or (subset == 'training' and not selected <= set(names)):
            raise ValueError('Unexpected evaluation camera inventory')
        data_hashes = {str(data / 'sparse/0' / name): sha(data / 'sparse/0' / name) for name in ('images.txt', 'cameras.txt')}
        for label, binary in [('baseline', baseline), ('candidate', candidate)]:
            label_path = output / f'{subset}-{label}'
            command = [str(binary), 'train', '360-camera', '--resume', str(checkpoint), '--data', str(data), '--output-dir-prefix', str(output), '--output-dir-name', label_path.name, '--num-iterations', str(step), '--steps-per-save', '0', '--disable-viewer', '1', '--save-eval-images', '1', '--eval-lpips', '0', '--eval-align', '0', '--mask-boundary-offset', '0', '--warp-to-pinhole', '0']
            elapsed = run(command, output, output / f'{subset}-{label}.log')
            text = (output / f'{subset}-{label}.log').read_text(errors='replace')
            if f'at step {step}' not in text or 'Eval: views to score: 36' not in text or list(label_path.glob('step-*.ckpt')):
                raise ValueError('Zero-step evaluation evidence missing')
            resolved = json.loads((label_path / 'config.json').read_text())
            diff = {k: [config.get(k), resolved.get(k)] for k in set(config) | set(resolved) if config.get(k) != resolved.get(k)}
            if set(diff) - {'data', 'output_dir_prefix', 'output_dir_name', 'resume', 'steps_per_save'}:
                raise ValueError(f'Unexpected config differences: {diff}')
            report['runs'][f'{subset}-{label}'] = {'command': command, 'elapsed_seconds': elapsed, 'config_differences': diff, 'data_pose_hashes': data_hashes}
            if hashes != {str(p): sha(p) for p in input_paths}: raise RuntimeError('Checkpoint changed during evaluation')
        rows = []; seams = []
        for i, name in enumerate(names):
            if subset == 'training' and name not in selected: continue
            reference = pixels.load(data / 'images' / name); mask = pixels.load(data / 'masks' / name, True)
            renders = []
            for label in ('baseline', 'candidate'):
                path = output / f'{subset}-{label}'
                saved_ref = pixels.load(path / f'eval-gt-{i:05d}.png'); saved_mask = pixels.load(path / f'eval-mask-{i:05d}.png', True)
                if not np.array_equal(mask, saved_mask) or np.max(np.abs(reference.astype(np.int16) - saved_ref.astype(np.int16))) > 1:
                    raise ValueError(f'Reference/mask mismatch: {subset} {label} {name}')
                renders.append(pixels.load(path / f'eval-render-{i:05d}.png'))
            row = pixels.score(reference, *renders, mask, mask); row['name'] = name; rows.append(row)
            edge = np.zeros_like(mask); edge[:, :16] = mask[:, :16]; edge[:, -16:] = mask[:, -16:]
            if np.any(edge >= 128): seams.append(pixels.score(reference, *renders, edge, edge))
        report['comparisons'][subset] = {'full': pixels.pool(rows), 'seam_16px': pixels.pool(seams) if seams else None, 'names': [r['name'] for r in rows]}
        (output / 'report.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    print(json.dumps(report['comparisons'], indent=2))


if __name__ == '__main__': main()
