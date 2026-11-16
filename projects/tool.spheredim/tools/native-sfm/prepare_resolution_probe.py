#!/usr/bin/env python3
"""Build paired resolution datasets from reviewed physical-lens observations; do not train."""
import argparse
import copy
import json
import os
from pathlib import Path
import shutil
import struct

import cv2
import numpy as np
import prepare_splat as splat

RESERVE = 35 * 1024**3
BUDGET = 300 * 1024**2


def write_model(destination, cameras, poses, points, rigs, width):
    destination.mkdir(parents=True)
    with (destination / 'cameras.bin').open('wb') as f:
        f.write(struct.pack('<Q', len(cameras)))
        for camera_id, old_width, old_height, a, b in cameras:
            if (old_width, old_height, a, b) != (1024, 512, 1024, 512):
                raise ValueError('Unexpected ERP camera parameters')
            f.write(struct.pack('<iiQQ2d', camera_id, 17, width, width // 2, width, width // 2))
    with (destination / 'images.bin').open('wb') as f:
        f.write(struct.pack('<Q', len(poses)))
        for name, row in poses:
            f.write(struct.pack('<i7di', *row))
            f.write(name.encode() + b'\0')
            f.write(struct.pack('<Q', 0))
    os.link(points, destination / 'points3D.bin')
    os.link(rigs, destination / 'rigs.txt')


def prepare(dataset, model, binary, output, selected, interval):
    dataset, model, binary = (Path(p).resolve(strict=True) for p in (dataset, model, binary))
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError(output)
    if shutil.disk_usage(output.parent).free < RESERVE + BUDGET:
        raise RuntimeError('Need 35 GiB reserve plus 300 MiB budget')
    meta = json.loads((dataset / 'manifest.json').read_text())
    probe_path = Path(meta['source_manifest']).resolve(strict=True)
    if splat.digest(probe_path) != meta['source_manifest_sha256']:
        raise ValueError('Source probe manifest hash mismatch')
    probe = json.loads(probe_path.read_text())
    originals = {x['frame']: x for x in probe['frames']}
    frames = {x['source_frame']: x for x in meta['frames']}
    if len(selected) != 16 or len(set(selected)) != 16 or not set(selected) <= frames.keys():
        raise ValueError('Select exactly 16 distinct reviewed timestamps')
    cameras, poses, points = splat.read_model(model)
    names = {f'cam{lens}/frame_{n:06d}.png' for n in selected for lens in (0, 1)}
    poses = [(name, row) for name, row in poses if name in names]
    if len(poses) != 32 or {name for name, _ in poses} != names or not points:
        raise ValueError('Source model does not contain every selected pose')
    # One common split is generated from selected timestamp order in both arms.
    splat.split_frames(selected, interval)
    output.mkdir()
    (output / 'INCOMPLETE').write_text('Preparation did not complete\n')
    manifests = {}
    for width in (1024, 2048):
        root = output / str(width)
        for folder in ('images', 'masks'):
            for lens in ('cam0', 'cam1'):
                (root / 'source' / folder / lens).mkdir(parents=True)
        manifests[width] = {'resolution': [width, width // 2], 'frames': [],
                            'source_manifest_sha256': splat.digest(dataset / 'manifest.json'),
                            'probe_manifest_sha256': splat.digest(probe_path),
                            'original_model_sha256': {name: splat.digest(model / name) for name in ('cameras.bin', 'images.bin', 'points3D.bin', 'rigs.txt')},
                            'model_note': 'Selected image poses and shared full-model seed; point tracks are retained and this subset is for splat preparation, not general SfM.',
                            'mask_semantics': 'reviewed 1024 keep expanded to 2x2 children and intersected with original physical support' if width == 2048 else 'original reviewed keep'}
    for n in sorted(selected):
        entry = frames[n]
        original = originals[n]
        if entry['timestamp_microseconds'] != original['timestamp_microseconds'] or entry['source_packet_pts'] != original['source_packet_pts']:
            raise ValueError(f'Timestamp mismatch at {n}')
        copies = {width: copy.deepcopy(entry) for width in (1024, 2048)}
        for i in (0, 1):
            lens = f'cam{i}'; name = f'frame_{n:06d}.png'; info = entry['lenses'][lens]
            low_image = dataset / 'images' / lens / name
            low_mask = dataset / 'masks' / lens / name
            original_image, original_mask = Path(original[f'lens{i}']), Path(original[f'mask{i}'])
            for path, expected in ((low_image, info['image_sha256']), (low_mask, info['mask_sha256']),
                                   (original_image, info['image_source_sha256']), (original_mask, info['support_source_sha256'])):
                if splat.digest(path) != expected:
                    raise ValueError(f'Input hash mismatch: {path}')
            low = cv2.imread(str(low_mask), cv2.IMREAD_GRAYSCALE)
            support = cv2.imread(str(original_mask), cv2.IMREAD_GRAYSCALE)
            image = cv2.imread(str(original_image), cv2.IMREAD_COLOR)
            if low is None or low.shape != (512, 1024) or support is None or support.shape != (1024, 2048) or image is None or image.shape != (1024, 2048, 3):
                raise ValueError('Unexpected input image dimensions')
            keep = np.repeat(np.repeat(low == 255, 2, axis=0), 2, axis=1) & (support == 255)
            image[~keep] = 0
            for folder, path in (('images', low_image), ('masks', low_mask)):
                os.link(path, output / '1024' / 'source' / folder / lens / name)
            for folder, data in (('images', image), ('masks', keep.astype(np.uint8) * 255)):
                dest = output / '2048' / 'source' / folder / lens / name
                if not cv2.imwrite(str(dest), data):
                    raise RuntimeError(f'Could not write {dest}')
                copies[2048]['lenses'][lens]['image_sha256' if folder == 'images' else 'mask_sha256'] = splat.digest(dest)
            if sum(p.stat().st_size for p in output.rglob('*') if p.is_file() and p.stat().st_nlink == 1) > BUDGET or shutil.disk_usage(output).free < RESERVE:
                raise RuntimeError('Output budget or free-space reserve exceeded')
        for width in (1024, 2048):
            manifests[width]['frames'].append(copies[width])
    for width in (1024, 2048):
        root = output / str(width)
        (root / 'source' / 'manifest.json').write_text(json.dumps(manifests[width], indent=2) + '\n')
        write_model(root / 'model', cameras, poses, model / 'points3D.bin', model / 'rigs.txt', width)
        splat.prepare(root / 'source', root / 'model', binary, root / 'prepared', f'resolution-{width}-run', interval)
        if sum(p.stat().st_size for p in output.rglob('*') if p.is_file() and p.stat().st_nlink == 1) > BUDGET or shutil.disk_usage(output).free < RESERVE:
            raise RuntimeError('Output budget or free-space reserve exceeded')
    (output / 'INCOMPLETE').unlink()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('dataset', type=Path); p.add_argument('model', type=Path); p.add_argument('binary', type=Path); p.add_argument('output', type=Path)
    p.add_argument('--frames', type=int, nargs=16, required=True); p.add_argument('--holdout-every', type=int, default=8)
    a = p.parse_args(); prepare(a.dataset, a.model, a.binary, a.output, a.frames, a.holdout_every)


if __name__ == '__main__':
    main()
