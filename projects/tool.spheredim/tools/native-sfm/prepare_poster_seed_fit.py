#!/usr/bin/env python3
"""Prepare matched original-camera point-seed diagnostic; never train."""
import argparse
import hashlib
import json
import os
from pathlib import Path

import numpy as np
import prepare_capture_group as group


def cloud_info(path):
    with path.open() as stream:
        header = []
        for line in stream:
            header.append(line.strip())
            if line.strip() == 'end_header':
                break
        if len(header) < 3 or header[:2] != ['ply', 'format ascii 1.0'] or not header[2].startswith('element vertex '):
            raise ValueError('Expected an ASCII point cloud PLY')
        count = int(header[2].split()[-1])
        if count < 2 or count > 6505:
            raise ValueError('Point count must be between 2 and the available cap')
        if header[3:] != ['property float x', 'property float y', 'property float z',
                           'property uchar red', 'property uchar green', 'property uchar blue', 'end_header']:
            raise ValueError('Unexpected point cloud fields')
        data = np.loadtxt(stream)
    if data.shape != (count, 6) or not np.isfinite(data).all():
        raise ValueError('Invalid point cloud shape or values')
    rgb = data[:, 3:]
    if np.any(rgb < 0) or np.any(rgb > 255) or np.any(rgb != np.floor(rgb)) or len(np.unique(rgb, axis=0)) < 2:
        raise ValueError('Invalid or uniform RGB would not preserve source colors')
    xyz = data[:, :3]
    if len(np.unique(xyz, axis=0)) != count:
        raise ValueError('Duplicate XYZ points cannot define positive local scales')
    neighbors = min(4, count-1)
    distances = []
    # Bound memory independently of the complete N-by-N-by-3 cloud size.
    for start in range(0, count, 64):
        chunk = xyz[start:start+64]
        d2 = np.zeros((len(chunk), count))
        for axis in range(3):
            d2 += (chunk[:, None, axis] - xyz[None, :, axis])**2
        d2[np.arange(len(chunk)), start+np.arange(len(chunk))] = np.inf
        nearest = np.partition(d2, neighbors-1, axis=1)[:, :neighbors]
        distances.extend(np.sqrt(np.mean(nearest, axis=1)))
    scale = .35*np.asarray(distances)
    if not np.isfinite(scale).all() or np.any(scale <= 0):
        raise ValueError('Invalid predicted local scales')
    return {'points': len(data), 'scale_init': .35, 'scale_min_median_max': [float(np.min(scale)), float(np.median(scale)), float(np.max(scale))],
            'scale_note': 'Model/world units; scale_init times RMS distance to up to four nearest new cloud points.'}


def prepare(manifest, cloud, source_ply, prior_plan, output, expected_cloud):
    manifest, cloud, source_ply, prior_plan = (Path(x).resolve(strict=True) for x in (manifest, cloud, source_ply, prior_plan))
    output = Path(output).resolve()
    if group.sha(cloud) != expected_cloud:
        raise ValueError('Point cloud differs from reviewed input')
    info = cloud_info(cloud)
    if info['points'] > 6505:
        raise ValueError('Point cloud exceeds existing cap')
    old = json.loads(prior_plan.read_text())
    if group.sha(source_ply) != old['source_ply_sha256']:
        raise ValueError('Original PLY mismatch')
    # Existing group fit config has raw appearance off, no refinement/noise.
    command = old['zero_command'].copy()
    if Path(command[command.index('--init-ply')+1]).resolve() != source_ply or group.sha(command[0]) != old['binary_sha256']:
        raise ValueError('Prior command PLY path or binary hash differs')
    names = [f'train_{n:06}_cam0.png' for n in (1465,1475,1485,1490,1495,1500,1505,1515,1525,1535,1545)]
    eval_names = ['eval_001440_cam0.png', 'eval_001560_cam0.png']
    staged = group.prepare(manifest, output, names, eval_names)
    data = output/'data'
    original = 'train_001500_cam0.png'
    alias = 'eval_001500_cam0.png'
    for folder in ('images', 'masks'):
        os.link(data/folder/original, data/folder/alias)
    rows = (data/'sparse/0/images.txt').read_text().splitlines()
    matches = [line.split() for line in rows if line.split() and line.split()[-1] == original]
    if len(matches) != 1:
        raise ValueError('Training diagnostic pose not unique')
    row = matches[0].copy()
    used = {int(line.split()[0]) for line in rows if len(line.split()) == 10}
    new_id = max(used)+1
    row[0] = str(new_id)
    row[-1] = alias
    with (data/'sparse/0/images.txt').open('a') as f:
        f.write(' '.join(row)+'\n\n')
    if not all(os.path.samefile(data/folder/original, data/folder/alias) for folder in ('images', 'masks')):
        raise ValueError('Diagnostic alias does not preserve source identity')
    for flag, value in {'--data': str(data), '--output-dir-prefix': str(output),
                        '--output-dir-name': 'zero-control', '--num-iterations': '0',
                        '--steps-per-save': '0', '--seed-pointcloud': str(cloud)}.items():
        command[command.index(flag)+1] = value
    command += ['--init-ply-add-points', '0'] if '--init-ply-add-points' not in command else []
    command[command.index('--init-ply-add-points')+1] = '0'
    candidate = command.copy()
    candidate[candidate.index('--output-dir-name')+1] = 'zero-candidate'
    candidate[candidate.index('--steps-per-save')+1] = '1'
    candidate[candidate.index('--init-ply-add-points')+1] = '1'
    plan = {'description': 'Fixed-plane hypothesis, not unique multi-view depth. Frame 1500 is used to create the cloud and is a training diagnostic, not a heldout.',
            'source_ply': str(source_ply), 'source_ply_sha256': group.sha(source_ply),
            'cloud': str(cloud), 'cloud_sha256': group.sha(cloud), 'cloud_info': info,
            'original_splats': 293495, 'candidate_splats': 293495+info['points'], 'training_images': 11,
            'evaluation_names': ['eval_001440_cam0.png', alias, 'eval_001560_cam0.png'],
            'alias_pose_id': new_id, 'staging': staged,
            'control_zero_command': command, 'candidate_zero_command': candidate,
            'limits': {'combined_bytes': 190000000, 'gpu_seconds_total': 300, 'task_bytes': 15000000000,
                       'support_bytes': 2000000000, 'minimum_free_bytes': 35*1024**3},
            'status': 'prepared for zero checks only; fitting requires owner review'}
    (output/'plan.json').write_text(json.dumps(plan, indent=2)+'\n')
    return plan


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('manifest', 'cloud', 'source_ply', 'prior_plan', 'output'):
        p.add_argument(name, type=Path)
    p.add_argument('--cloud-sha256', required=True)
    a = p.parse_args()
    print(json.dumps(prepare(a.manifest, a.cloud, a.source_ply, a.prior_plan, a.output, a.cloud_sha256)['cloud_info']))


if __name__ == '__main__':
    main()
