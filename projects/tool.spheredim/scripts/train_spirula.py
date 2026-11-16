"""Run guarded native-equirectangular Spirula training with local progress."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('executable', type=Path)
    parser.add_argument('dataset', type=Path)
    parser.add_argument('output', type=Path, help='New run directory')
    parser.add_argument('progress', type=Path, help='New progress JSON path')
    parser.add_argument('log', type=Path, help='New log path')
    parser.add_argument('--iterations', type=int, default=10000)
    parser.add_argument('--save-every', type=int, default=1000)
    parser.add_argument('--max-splats', type=int, default=500000)
    args = parser.parse_args()
    if min(args.iterations, args.save_every, args.max_splats) < 1:
        parser.error('Iterations, save interval, and splat cap must be positive')
    if any(path.exists() for path in (args.output, args.progress, args.log)):
        parser.error('Output, progress, and log paths must be new')
    if not args.executable.is_file() or not (args.dataset / 'manifest.json').is_file():
        parser.error('Executable or dataset manifest not found')
    if not all(path.parent.is_dir() for path in (args.output, args.progress, args.log)):
        parser.error('Parent directories must exist')
    manifest = json.loads((args.dataset / 'manifest.json').read_text())
    expected = sum(frame['split'] == 'train' for frame in manifest['frames'])
    if expected < 2:
        parser.error('Dataset needs at least two training panoramas')
    command = [str(args.executable.resolve()), 'train', '360-camera', '--data', str(args.dataset.resolve()),
        '--output-dir-prefix', str(args.output.parent.resolve()), '--output-dir-name', args.output.name,
        '--seed-pointcloud', 'seed.ply', '--num-iterations', str(args.iterations),
        '--steps-per-save', str(args.save_every), '--save-full-checkpoint', '1',
        '--disable-viewer', '1', '--cap-max', str(args.max_splats), '--load-masks', '1',
        '--apply-loss-for-mask', '0', '--flip-mask', '0',
        '--warp-spherical-to-pinhole', '0', '--warp-to-pinhole', '0']
    state = {'stage': 'gaussian_training', 'status': 'starting', 'iteration': 0,
        'total': args.iterations, 'elapsed_seconds': 0., 'eta_seconds': None, 'splats': None,
        'error': None, 'output_dir': str(args.output.resolve()), 'checkpoints': [],
        'camera_count': None, 'camera_count_after_splitting': None, 'log': str(args.log.resolve())}
    started = time.monotonic()
    def publish():
        state['checkpoints'] = [str(p.resolve()) for p in sorted(args.output.glob('step-*.ckpt'))] if args.output.exists() else []
        fd, name = tempfile.mkstemp(prefix='.progress-', suffix='.tmp', dir=args.progress.parent)
        try:
            with os.fdopen(fd, 'w') as file:
                json.dump(state, file, indent=2); file.write('\n'); file.flush(); os.fsync(file.fileno())
            os.replace(name, args.progress)
        finally:
            if os.path.exists(name): os.unlink(name)
    def seconds(value):
        if '--' in value: return None
        return sum(float(v)*60**i for i,v in enumerate(reversed(value.split(':'))))
    publish(); process = None; seen = False
    try:
        with args.log.open('x', buffering=1) as log:
            env = dict(os.environ, SS_LANG='en')
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, env=env)
            state.update(status='running', pid=process.pid); publish()
            for line in process.stdout:
                log.write(line); print(line, end='', flush=True)
                match = re.search(r'Cameras:\s*(\d+)\s*\((\d+) after splitting\)', line)
                if match:
                    seen = True
                    state['camera_count'],state['camera_count_after_splitting'] = map(int,match.groups())
                    if state['camera_count'] != expected or state['camera_count_after_splitting'] != expected:
                        state.update(status='error', error=f'Camera count mismatch: expected {expected}, got {match[1]} to {match[2]}');publish();process.kill();break
                match = re.search(r'step\s+(\d+)/(\d+).*?splats\s+(\d+).*?elapsed\s+([^\s|]+)\s*\|\s*ETA\s+([^\s\]]+)', line)
                if match:
                    state.update(iteration=int(match[1]), splats=int(match[3]), elapsed_seconds=seconds(match[4]), eta_seconds=seconds(match[5]))
                publish()
            exitcode = process.wait();state['exit_code'] = exitcode
            if state['status'] != 'error':
                if exitcode or not seen or state['iteration'] != args.iterations:
                    state.update(status='error', error=f'Trainer exited {exitcode}; cameras observed={seen}, step={state["iteration"]}/{args.iterations}')
                else: state.update(status='complete', eta_seconds=0.)
            publish()
    except BaseException as error:
        if process and process.poll() is None: process.terminate(); process.wait()
        state.update(status='cancelled' if isinstance(error, KeyboardInterrupt) else 'error',
            error=None if isinstance(error, KeyboardInterrupt) else f'{type(error).__name__}: {error}', elapsed_seconds=time.monotonic()-started)
        publish(); raise
    if state['status'] != 'complete': sys.exit(1)


if __name__ == '__main__': main()
