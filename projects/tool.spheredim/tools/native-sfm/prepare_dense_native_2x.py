#!/usr/bin/env python3
"""Prepare dense native 2048 ERP splat inputs with bounded temporary exports."""
import copy
from decimal import Decimal
import json
import os
from pathlib import Path
import shutil
import sys

import cv2
import numpy as np
import prepare_dense_rig as rig
import prepare_resolution_probe as resolution
import prepare_splat as splat

RESERVE = 35 * 1024**3
BUDGET = 1638 * 1024**2
rig.BUDGET = BUDGET


def keep_mask(low, support):
    if low.shape != (512, 1024) or support.shape != (1024, 2048):
        raise ValueError('Unexpected mask dimensions')
    if not np.isin(low, (0, 255)).all() or not np.isin(support, (0, 255)).all():
        raise ValueError('Masks must be binary')
    return np.repeat(np.repeat(low == 255, 2, axis=0), 2, axis=1) & (support == 255)


def check(root):
    if rig.disk_usage(root, set()) > BUDGET or shutil.disk_usage(root).free < RESERVE:
        raise RuntimeError('Native dataset output budget or free reserve exceeded')


def prepare(base, output):
    base, output = Path(base).resolve(strict=True), Path(output).resolve()
    old = base / 'rig-dense-splat-6000-20261115'; source = old / 'source'
    baseline = json.loads((source / 'manifest.json').read_text())
    probe_path = base / 'rig-probes-reviewed-20261115/manifest.json'
    if splat.digest(probe_path) != baseline['source_manifest_sha256']:
        raise ValueError('Original native probes manifest changed')
    probe = json.loads(probe_path.read_text()); recording = Path(probe['source'])
    native = Path(probe['provenance']['native_extension_path'])
    if splat.digest(recording) != probe['source_sha256'] or splat.digest(native) != probe['provenance']['native_extension_sha256']:
        raise ValueError('Recording or native exporter changed')
    records = baseline['frames']; ids = [x['source_frame'] for x in records]
    if len(ids) != 412 or ids != sorted(set(ids)):
        raise ValueError('Expected 412 ordered dense timestamps')
    if output.exists() or shutil.disk_usage(base).free < RESERVE + BUDGET:
        raise ValueError('Output exists or reserve and data cap unavailable')
    streams, packets = rig.packet_map(recording)
    for row in records:
        if rig.matched_pts(row['timestamp_microseconds'], streams, packets) != row['source_packet_pts']:
            raise ValueError('Source packet PTS changed')
    orig = {x['frame']: x for x in probe['frames']}; by_id = {x['source_frame']: x for x in records}
    if not set(orig).issubset(ids): raise ValueError('Baseline probe frame missing')
    output.mkdir(); (output / 'INCOMPLETE').write_text('Preparation not complete\n')
    dataset = output / 'source'
    for folder in ('images', 'masks'):
        for lens in ('cam0', 'cam1'): (dataset / folder / lens).mkdir(parents=True)
    env = os.environ.copy(); env.pop('SPHEREDIM_LENS1_INVERSE_QUAT_WXYZ', None); env.pop('SPHEREDIM_OBSERVATION_MODE', None)
    env['PYTHONPATH'] = str(native.parent.parent); env['UV_CACHE_DIR'] = '/private/tmp/insv-uv-cache'
    exporter = Path(__file__).with_name('export_timestamp_probes.py').resolve()
    provenance = []; output_rows = []
    def process(frame):
        n = frame['frame']; row = copy.deepcopy(by_id[n])
        if frame['timestamp_microseconds'] != row['timestamp_microseconds']: raise ValueError('Export PTS differs')
        for i in (0, 1):
            lens = f'cam{i}'; name = f'frame_{n:06d}.png'; low_path = source / 'masks' / lens / name
            if splat.digest(low_path) != row['lenses'][lens]['mask_sha256']: raise ValueError('Reviewed keep mask changed')
            for mode in (f'lens{i}', f'mask{i}'):
                if splat.digest(Path(frame[mode])) != frame[mode + '_sha256']: raise ValueError('Native probe hash changed')
            image = cv2.imread(frame[f'lens{i}']); support = cv2.imread(frame[f'mask{i}'], 0); low = cv2.imread(str(low_path), 0)
            if image is None or image.shape != (1024, 2048, 3) or low is None or support is None: raise ValueError('Invalid native source')
            keep = keep_mask(low, support); image[~keep] = 0
            for folder, data, key in (('images', image, 'image_sha256'), ('masks', keep.astype(np.uint8)*255, 'mask_sha256')):
                dst = dataset / folder / lens / name
                if not cv2.imwrite(str(dst), data): raise RuntimeError('PNG write failed')
                row['lenses'][lens][key] = splat.digest(dst)
                if not np.array_equal(cv2.imread(str(dst), cv2.IMREAD_UNCHANGED), data): raise ValueError('PNG verification failed')
            row['lenses'][lens]['native_image_sha256'] = frame[f'lens{i}_sha256']
            row['lenses'][lens]['native_support_sha256'] = frame[f'mask{i}_sha256']
        output_rows.append(row); check(output)
    for n in ids:
        if n in orig: process(orig[n])
    remaining = [n for n in ids if n not in orig]
    for start in range(0, len(remaining), 8):
        batch = remaining[start:start+8]; temp = output / 'raw-batch'; times = [str(Decimal(by_id[n]['timestamp_microseconds']) / Decimal(1_000_000)) for n in batch]
        cmd = ['uv','run','--offline','--isolated','--no-project','--python','3.12','--with','numpy','--with','pillow','python',str(exporter),'--source',str(recording),'--output',str(temp),'--indices',*map(str,batch),'--timestamps',*times,'--width','2048']
        rig.monitor(cmd, env, output, set(), output / f'batch-{start//8:03d}.log', 300)
        meta = json.loads((temp/'manifest.json').read_text()); provenance.append({'manifest_sha256':splat.digest(temp/'manifest.json'),'frames':[{k:f[k] for k in ('frame','timestamp_microseconds','lens0_sha256','lens1_sha256','mask0_sha256','mask1_sha256')} for f in meta['frames']]})
        if [f['frame'] for f in meta['frames']] != batch: raise ValueError('Wrong batch frames')
        for f in meta['frames']: process(f)
        # Persist completed source hashes before deleting the raw temporary batch.
        (output / 'batch-provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
        shutil.rmtree(temp); check(output)
    output_rows.sort(key=lambda x:x['source_frame'])
    meta = {**baseline,'resolution':[2048,1024], 'frames':output_rows, 'status':'Native 2048 controlled candidate; conservative 1024 keep intersected with native physical support', 'exporter_sha256':splat.digest(exporter), 'batch_provenance':provenance}
    (dataset/'manifest.json').write_text(json.dumps(meta,indent=2)+'\n')
    model = base/'rig-density-explicit-dense-20261115/workspace/sparse/0'; cams, poses, points = splat.read_model(model)
    if len(poses)!=824 or len(points)==0: raise ValueError('Incomplete dense model')
    resolution.write_model(output/'model', cams, poses, model/'points3D.bin', model/'rigs.txt', 2048)
    binary = Path(json.loads((old/'plan.json').read_text())['command'][0]); m = splat.prepare(dataset, output/'model', binary, output/'prepared', 'run', 24, 6000, 1000)
    previous = json.loads((old/'prepared/manifest.json').read_text())
    if m['heldout_evaluation_order'] != previous['heldout_evaluation_order'] or len(m['frames']) != 824: raise ValueError('Evaluation split changed')
    check(output); (output/'INCOMPLETE').unlink()
    return {'frames':len(output_rows),'camera_count':len(m['frames']),'heldouts':len(m['heldout_evaluation_order']),'output_bytes':rig.disk_usage(output,set()),'status':'prepared; no training'}


if __name__ == '__main__':
    if len(sys.argv)!=3: raise SystemExit('usage: prepare_dense_native_2x.py RECORDING_DIR OUTPUT')
    print(json.dumps(prepare(sys.argv[1],sys.argv[2]),indent=2))
