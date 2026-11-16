#!/usr/bin/env python3
"""Run matched global SfM with co-located and separated physical lens centers."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import time


def digest(file):
    return hashlib.sha256(file.read_bytes()).hexdigest()


def publish(file, data):
    temp = file.with_name(file.name + '.writing')
    temp.write_text(json.dumps(data, indent=2) + '\n')
    temp.replace(file)


def command(binary, dataset, workspace, config, standalone=False, ba_real="float"):
    return [str(binary), *([] if standalone else ['sfm']), 'auto', str(dataset / 'images'), '-o', str(workspace),
            '--manifest', str(config), '--mapper', 'global',
            '--camera-model', 'equirectangular', '--camera-mode', 'folder',
            '--masks', str(dataset / 'masks'), '--feature-masks', str(dataset / 'feature-masks'),
            '--sequence', 'cam0,cam1', '--features', 'sift', '--matcher', 'bruteforce',
            '--pairs', 'exhaustive', '--data-type', 'video', '--quality', 'medium',
            '--max-image-size', '1024', '--threads', '4', '--decode-threads', '2',
            '--no-refine-rigs', '--no-orient', '--exif-orientation', 'none',
            '--no-manage', '--seam-weld', '0', '--ba-real', ba_real, '--ba-real-coarse', ba_real,
            '--progress-dir', str(workspace / 'progress')]


def size(root):
    return sum(p.stat().st_size for p in root.rglob('*') if p.is_file())


def validate_configs(dataset, arms):
    """Only cam1 translation may differ between the controlled runs."""
    reference = None
    for arm in arms:
        config = json.loads((dataset / f'rig-{arm}.json').read_text())
        member = config['rigs'][0]['members'][1]
        translation = member.pop('translation')
        if len(translation) != 3 or not all(math.isfinite(x) for x in translation):
            raise ValueError(f'Invalid translation in {arm}')
        if member['prefix'] != 'cam1' or not member['fixed'] or member['refine'] != 'none':
            raise ValueError(f'Expected fixed cam1 extrinsics in {arm}')
        if reference is not None and config != reference:
            raise ValueError('Rig configurations must differ only in cam1 translation')
        reference = config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', type=Path)
    parser.add_argument('dataset', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--status', type=Path)
    parser.add_argument('--standalone', action='store_true', help='Executable is spirula-sfm rather than the full application')
    parser.add_argument('--rotation-priors', type=Path, help='Calibrated camera-to-world quaternion CSV for the patched backend')
    parser.add_argument('--telemetry', type=Path, help='Original sensor-bearing video; enables stock gyro and accelerometer factors')
    parser.add_argument('--ba-real', choices=('float', 'double', 'df', 'cpu'), default='float',
                        help='Bundle-adjustment scalar/backend for both normal and coarse solves')
    parser.add_argument('--arms', nargs='+', choices=('zero', 'separated', 'fitted-metric', 'metadata'), default=['zero', 'separated'])
    parser.add_argument('--timeout-seconds', type=int, default=600)
    args = parser.parse_args()
    args.binary = args.binary.resolve()
    args.dataset = args.dataset.resolve()
    args.output = args.output.resolve()
    if len(set(args.arms)) != len(args.arms):
        parser.error('Run names must be unique')
    for file in (args.binary, args.dataset / 'manifest.json', *(args.dataset / f'rig-{arm}.json' for arm in args.arms)):
        if not file.is_file():
            parser.error('Missing file: ' + str(file))
    if args.telemetry:
        args.telemetry = args.telemetry.resolve()
        if not args.telemetry.is_file():
            parser.error('Telemetry source must be an existing file')
    if args.rotation_priors and args.telemetry:
        parser.error('Use calibrated rotation priors or native telemetry, not both')
    if args.rotation_priors:
        args.rotation_priors = args.rotation_priors.resolve()
        if not args.rotation_priors.is_file():
            parser.error('Rotation priors must be an existing CSV file')
    validate_configs(args.dataset, args.arms)
    if args.output.exists():
        parser.error('Output must be new')
    if shutil.disk_usage(args.output.parent).free < 36 * 1024**3:
        parser.error('Need 35 GiB reserve plus 1 GiB experiment budget')
    args.output.mkdir()
    status = args.status or args.output / 'status.json'
    records = []
    inputs = {str(file.relative_to(args.dataset)): digest(file) for folder in ('images', 'masks', 'feature-masks', 'eval-masks') for file in sorted((args.dataset / folder).rglob('*.png'))}
    manifest = {'binary_sha256': digest(args.binary), 'dataset_manifest_sha256': digest(args.dataset / 'manifest.json'),
                'input_sha256': inputs, 'comparison': 'same images, masks, intrinsics and rig rotation; only fixed cam1 translation varies', 'arms': args.arms,
                'mapper': 'global', 'ba_scalar': args.ba_real, 'runs': records}
    if args.rotation_priors:
        manifest['rotation_priors'] = {'path': str(args.rotation_priors), 'sha256': digest(args.rotation_priors)}
    if args.telemetry:
        stat = args.telemetry.stat()
        manifest['telemetry'] = {'path': str(args.telemetry), 'size_bytes': stat.st_size, 'mtime_ns': stat.st_mtime_ns, 'sensor_gauge': 'up', 'note': 'Stock IMU includes gyro and accelerometer BA factors; not a rotation-only comparison'}
    try:
        for index, arm in enumerate(args.arms):
            config = args.dataset / f'rig-{arm}.json'
            work = args.output / arm
            work.mkdir()
            cmd = command(args.binary, args.dataset, work, config, args.standalone, args.ba_real)
            if args.telemetry:
                cmd.extend(['--telemetry', str(args.telemetry), '--sensor-gauge', 'up', '--metric-gps', 'none'])
            if args.rotation_priors:
                cmd.extend(['--rotation-priors', str(args.rotation_priors)])
            record = {'arm': arm, 'command': cmd, 'rig_config_sha256': digest(config), 'status': 'running'}
            records.append(record)
            publish(args.output / 'manifest.json', manifest)
            publish(status, {'status': 'running', 'stage': f'Rig comparison: {arm} baseline', 'current': index, 'total': len(args.arms)})
            start = time.monotonic()
            with (work / 'run.log').open('w') as log:
                child = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
                try:
                    while child.poll() is None:
                        if time.monotonic() - start > args.timeout_seconds:
                            raise RuntimeError('Run time budget exceeded')
                        if shutil.disk_usage(args.output).free < 35 * 1024**3:
                            raise RuntimeError('Free disk crossed 35 GiB reserve')
                        if size(args.output) > 512 * 1024**2:
                            raise RuntimeError('Run output crossed 512 MiB budget')
                        time.sleep(2)
                finally:
                    if child.poll() is None:
                        child.terminate()
                        try:
                            child.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            child.kill()
                            child.wait()
            record.update(returncode=child.returncode, elapsed_seconds=time.monotonic()-start, output_bytes=size(work), status='completed' if child.returncode == 0 else 'failed')
            publish(args.output / 'manifest.json', manifest)
            if child.returncode:
                raise RuntimeError(f'{arm} SfM failed; see {work / "run.log"}')
            print(json.dumps(record), flush=True)
        for rel, expected in inputs.items():
            if digest(args.dataset / rel) != expected:
                raise RuntimeError('Input changed during comparison: ' + rel)
        if args.rotation_priors and digest(args.rotation_priors) != manifest['rotation_priors']['sha256']:
            raise RuntimeError('Rotation priors changed during reconstruction')
        publish(status, {'status': 'complete', 'stage': 'Camera pose estimation finished', 'current': len(args.arms), 'total': len(args.arms)})
    except BaseException as error:
        publish(status, {'status': 'failed', 'stage': 'Rig comparison', 'error': str(error)})
        raise


if __name__ == '__main__':
    main()
