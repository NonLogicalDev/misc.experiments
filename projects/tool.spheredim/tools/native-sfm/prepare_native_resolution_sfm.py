#!/usr/bin/env python3
"""Stage native 2x rig SfM inputs without copying source images or masks."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil

import cv2
import numpy as np


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1048576), b''): h.update(chunk)
    return h.hexdigest()


def prepare(native, old, pair_file, binary, output):
    native, old, pair_file, binary = (p.resolve(strict=True) for p in (native, old, pair_file, binary))
    output = output.resolve()
    if output.exists() or shutil.disk_usage(output.parent).free < 35 * 1024**3 + 64 * 1024**2:
        raise ValueError('Output exists or reserve plus staging budget unavailable')
    images = sorted(p.relative_to(native / 'images') for p in (native / 'images').rglob('*.png'))
    old_images = sorted(p.relative_to(old / 'images') for p in (old / 'images').rglob('*.png'))
    if not images or images != old_images: raise ValueError('Physical-lens image inventories differ or are empty')
    pairs = {(str(p.parent), p.name) for p in images}
    if any(p.parent.as_posix() not in ('cam0', 'cam1') or ('cam1' if p.parent.as_posix() == 'cam0' else 'cam0', p.name) not in pairs for p in images):
        raise ValueError('Expected synchronized cam0/cam1 image pairs')
    if any(not (native / 'masks' / p).is_file() or not (old / 'feature-masks' / p).is_file() for p in images): raise ValueError('Missing validity or feature guard mask')
    output.mkdir(); (output / 'INCOMPLETE').write_text('Input staging not verified\n')
    rows = []; generated = 0
    for name in images:
        for folder in ('images', 'masks', 'feature-masks'): (output / folder / name.parent).mkdir(parents=True, exist_ok=True)
        for folder in ('images', 'masks'): os.link(native / folder / name, output / folder / name)
        old_guard = cv2.imread(str(old / 'feature-masks' / name), cv2.IMREAD_GRAYSCALE)
        mask = cv2.imread(str(native / 'masks' / name), cv2.IMREAD_GRAYSCALE)
        if old_guard is None or mask is None or old_guard.shape != (512, 1024) or mask.shape != (1024, 2048): raise ValueError(f'Mask size mismatch: {name}')
        if not np.isin(old_guard, (0, 255)).all() or not np.isin(mask, (0, 255)).all(): raise ValueError(f'Nonbinary mask: {name}')
        guard = cv2.bitwise_and(cv2.resize(old_guard, (2048, 1024), interpolation=cv2.INTER_NEAREST), mask)
        target = output / 'feature-masks' / name
        if not cv2.imwrite(str(target), guard): raise RuntimeError(f'Cannot write {target}')
        generated += target.stat().st_size
        if generated > 64 * 1024**2 or shutil.disk_usage(output).free < 35 * 1024**3: raise RuntimeError('Staging storage guard exceeded')
        rows.append({'name': str(name), 'image_sha256': digest(native / 'images' / name), 'validity_sha256': digest(native / 'masks' / name), 'old_feature_guard_sha256': digest(old / 'feature-masks' / name), 'feature_guard_sha256': digest(target), 'excluded_by_new_validity_pixels': int(np.count_nonzero((cv2.resize(old_guard, (2048, 1024), interpolation=cv2.INTER_NEAREST) != 0) & (mask == 0)))})
    for name in ('rig-metadata.json', 'rotation-priors.csv'): os.link(old / name, output / name)
    pairs = output / 'pairs.tsv'; os.link(pair_file, pairs)
    report = {'method': 'Native 2048x1024 physical-lens images and validity masks hardlinked; feature guard is nearest-neighbor 2x original 1024 guard intersected with the native high-resolution validity mask. The guard and validity remain separate. No pose or image resampling, no virtual views.', 'source': str(native), 'old_dataset': str(old), 'old_manifest_sha256': digest(old / 'manifest.json'), 'rig_sha256': digest(output / 'rig-metadata.json'), 'priors_sha256': digest(output / 'rotation-priors.csv'), 'pairs_sha256': digest(pairs), 'binary_sha256': digest(binary), 'count': len(rows), 'generated_guard_bytes': generated, 'frames': rows}
    (output / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n'); (output / 'INCOMPLETE').unlink()
    print(json.dumps({'count': len(rows), 'generated_guard_bytes': generated, 'validity_excluded_pixels': sum(x['excluded_by_new_validity_pixels'] for x in rows)}))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for n in ('native', 'old', 'pairs', 'binary', 'output'): p.add_argument(n, type=Path)
    a = p.parse_args(); prepare(a.native, a.old, a.pairs, a.binary, a.output)


if __name__ == '__main__': main()
