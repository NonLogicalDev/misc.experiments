#!/usr/bin/env -S uv run --script
"""Recreate 360DVO samples or render native equirectangular test footage."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request

PROJECT = Path(__file__).resolve().parent.parent
DATASET = 'https://huggingface.co/datasets/chris1004336379/360DVO/resolve/main/'
SCENARIOS = ('baseline', 'loop', 'dynamic', 'plain', 'repetitive', 'low_light')
SEQUENCES = ('tokyo_citywalk', 'bridge_night', 'grove', 'indoor_RC_car')


def download(url, destination, expected_sha256):
    request = urllib.request.Request(url, headers={'User-Agent': 'SphereDim-validation/1.0'})
    digest = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=90) as response, destination.open('xb') as output:
        while data := response.read(1024 * 1024):
            digest.update(data)
            output.write(data)
    if digest.hexdigest() != expected_sha256:
        destination.unlink()
        raise ValueError(f'SHA-256 mismatch for {url}')


def encode(ffmpeg, frames, extension, fps, output, filters=None):
    command = [ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin', '-n',
               '-framerate', str(fps), '-start_number', '0', '-i', str(frames / ('%06d.' + extension))]
    if filters:
        command += ['-vf', filters]
    command += ['-c:v', 'libx264', '-crf', '16', '-pix_fmt', 'yuv420p', str(output)]
    subprocess.run(command, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', type=Path, default=PROJECT, help='SphereDim project root')
    sub = parser.add_subparsers(dest='kind', required=True)
    synthetic = sub.add_parser('synthetic')
    synthetic.add_argument('scenario', choices=SCENARIOS)
    synthetic.add_argument('output', type=Path, help='new or empty output directory')
    synthetic.add_argument('--blender', default='blender')
    synthetic.add_argument('--ffmpeg', default='ffmpeg')
    real = sub.add_parser('real')
    real.add_argument('sequence', choices=SEQUENCES)
    real.add_argument('output', type=Path, help='new or empty output directory')
    real.add_argument('--ffmpeg', default='ffmpeg')
    args = parser.parse_args()
    project = args.project.resolve()
    if args.output.exists() and (not args.output.is_dir() or any(args.output.iterdir())):
        parser.error('Output must be a new or empty directory')
    if not shutil.which(args.ffmpeg):
        parser.error('FFmpeg with libx264 is required')
    if args.kind == 'synthetic' and not shutil.which(args.blender):
        parser.error('Blender is required')
    args.output.mkdir(parents=True, exist_ok=True)
    output = args.output.resolve()
    with tempfile.TemporaryDirectory(prefix='spheredim-frames-') as tmp:
        frames = Path(tmp)
        if args.kind == 'synthetic':
            subprocess.run([args.blender, '--background', '--factory-startup', '--python', str(project / 'tests/render_scene.py'), '--', str(frames), args.scenario], check=True)
            shutil.copyfile(frames / 'truth.json', output / 'truth.json')
            noise = 4 if args.scenario == 'low_light' else 2
            encode(args.ffmpeg, frames, 'png', 4 if args.scenario == 'baseline' else 8,
                   output / 'input.mp4', f'lenscorrection=k1=0.003:k2=0,noise=alls={noise}:allf=t+u')
        else:
            manifest_path = (project / 'validation/real/manifest.json' if args.sequence == 'tokyo_citywalk'
                             else project / 'validation/complexity' / args.sequence / 'manifest.json')
            manifest = json.loads(manifest_path.read_text())
            fps = manifest.get('source_fps', manifest.get('original_fps')) / manifest.get('sample_every', manifest.get('sample_every_source_frames'))
            for index, item in enumerate(manifest['frames']):
                source = item.get('source', item.get('source_path'))
                path = PurePosixPath(source)
                if path.is_absolute() or '..' in path.parts or path.suffix.lower() not in ('.jpg', '.jpeg'):
                    raise ValueError(f'Unexpected frame path: {source!r}')
                url = DATASET + urllib.parse.quote(str(path), safe='/')
                print(f'Downloading {index + 1}/{len(manifest["frames"])}: {source}', flush=True)
                download(url, frames / f'{index:06d}.jpg', item['sha256'])
                time.sleep(0.2)  # Be courteous to the dataset host.
            encode(args.ffmpeg, frames, 'jpg', fps, output / 'input.mp4')
    print(f'Wrote {output / "input.mp4"}')


if __name__ == '__main__':
    main()
