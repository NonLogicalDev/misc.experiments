"""Compare two trainer binaries from one saved checkpoint under a storage guard."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/native-sfm'))
import run_splat


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('checkpoint_run', type=Path)
    parser.add_argument('baseline', type=Path)
    parser.add_argument('candidate', type=Path)
    parser.add_argument('output', type=Path, help='New directory for both runs')
    args = parser.parse_args()
    checkpoint = args.checkpoint_run.resolve(strict=True)
    baseline, candidate = (p.resolve(strict=True) for p in (args.baseline, args.candidate))
    output = args.output.resolve()
    if output.exists() or not output.parent.is_dir():
        parser.error('Output must be a new path in an existing directory')
    inputs = [checkpoint / 'config.json', checkpoint / 'step-000010000.ckpt/splat.ply', checkpoint / 'step-000010000.ckpt/state.tar']
    hashes = {str(p): digest(p) for p in inputs}
    binaries = {str(p): digest(p) for p in (baseline, candidate)}
    if len(set(binaries.values())) != 2:
        parser.error('Baseline and candidate executables are identical')
    config = json.loads(inputs[0].read_text())
    if config['num_iterations'] != 10000 or config['cap_max'] != 300000:
        parser.error('Unexpected checkpoint configuration')
    data = Path(config['data']).resolve(strict=True)
    manifest = json.loads((data / 'manifest.json').read_text())
    expected = sum(frame['split'] == 'train' for frame in manifest['frames'])
    if expected != 240:
        parser.error('Unexpected training camera count')
    output.mkdir()
    report = {'checkpoint_hashes': hashes, 'binary_hashes': binaries, 'dataset_manifest_sha256': digest(data / 'manifest.json'), 'runs': {}}
    for label, executable in [('baseline', baseline), ('candidate', candidate)]:
        run = output / label
        command = [str(executable), 'train', '--resume', str(checkpoint), '--num-iterations', '10100', '--steps-per-save', '10100', '--save-full-checkpoint', '0', '--save-eval-images', '0', '--disable-viewer', '1', '--output-dir-prefix', str(output), '--output-dir-name', label]
        state = run_splat.monitor(command, run, output / f'{label}.status.json', output / f'{label}.log', expected, total=10100, timeout=600, limit=150 * 1024**2, reserve=35 * 1024**3)
        report['runs'][label] = {'command': command, 'status': state}
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        if state['status'] != 'complete':
            raise SystemExit(f'{label} failed: {state["error"]}')
        if hashes != {str(p): digest(p) for p in inputs}:
            raise RuntimeError('Checkpoint inputs changed during replay')


if __name__ == '__main__':
    main()
