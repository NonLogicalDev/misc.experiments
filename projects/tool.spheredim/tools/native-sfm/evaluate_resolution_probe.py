#!/usr/bin/env python3
"""Compare paired ERP renders at the lower source resolution without alignment."""
import argparse
import json
from pathlib import Path
import cv2
import numpy as np
import evaluate_splat as ev


def load(path, gray=False):
    img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE if gray else cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f'Cannot read image: {path}')
    return img


def evaluate(low_manifest, low_run, high_manifest, high_run, output, sheet):
    if output.exists() or sheet.exists():
        raise FileExistsError('Output already exists')
    lm = json.loads(low_manifest.read_text()); hm = json.loads(high_manifest.read_text())
    low = ev.mapping(lm, low_run); high = ev.mapping(hm, high_run)
    if len(low) != len(high) or not low:
        raise ValueError('Held-out inventories differ')
    rows = []; tiles = []
    for (i, a, lg, lr, lk), (j, b, hg, hr, hk) in zip(low, high):
        keys = ('name', 'source_name', 'source_frame', 'lens', 'timestamp_microseconds')
        if i != j or any(a[k] != b[k] for k in keys):
            raise ValueError('Held-out frame mapping differs')
        src = load(low_manifest.parent / 'images' / a['name']); mask = load(low_manifest.parent / 'masks' / a['name'], True)
        high_src = load(high_manifest.parent / 'images' / b['name']); high_mask = load(high_manifest.parent / 'masks' / b['name'], True)
        gt0, pred0, mask0 = load(lg), load(lr), load(lk, True)
        gt1, pred1, mask1 = load(hg), load(hr), load(hk, True)
        if src.shape != (512, 1024, 3) or mask.shape != (512, 1024) or any(x.shape != src.shape for x in (gt0, pred0)) or mask0.shape != mask.shape:
            raise ValueError('Invalid low-resolution images')
        if high_src.shape != (1024, 2048, 3) or high_mask.shape != (1024, 2048) or any(x.shape != high_src.shape for x in (gt1, pred1)) or mask1.shape != high_mask.shape:
            raise ValueError('Invalid high-resolution images')
        if not np.array_equal(mask, mask0) or not np.array_equal(high_mask, mask1) or not np.array_equal(high_mask, np.repeat(np.repeat(mask, 2, 0), 2, 1)):
            raise ValueError('Saved or paired masks differ')
        if np.abs(src.astype(np.int16)-gt0.astype(np.int16)).max() > 1 or np.abs(high_src.astype(np.int16)-gt1.astype(np.int16)).max() > 1:
            raise ValueError('Saved reference differs from source')
        down_src = cv2.resize(high_src, (1024,512), interpolation=cv2.INTER_AREA)
        if not np.array_equal(src[mask == 255], down_src[mask == 255]):
            raise ValueError('References differ on common valid pixels')
        down_render = cv2.resize(pred1, (1024,512), interpolation=cv2.INTER_AREA)
        results = []
        for rendered in (pred0, down_render):
            value = ev.metrics.frame_metrics(src, rendered, mask)
            value['spherical_ssim'] = ev.spherical_ssim(src, rendered, mask)
            results.append(value)
        rows.append({'name': a['name'], 'source_frame': a['source_frame'], 'lens': a['lens'],
                     'reference_sha256': ev.digest(low_manifest.parent / 'images' / a['name']),
                     'mask_sha256': ev.digest(low_manifest.parent / 'masks' / a['name']),
                     'low_render_sha256': ev.digest(lr), 'high_render_sha256': ev.digest(hr),
                     'low_saved_gt_sha256': ev.digest(lg), 'high_saved_gt_sha256': ev.digest(hg),
                     'low_saved_mask_sha256': ev.digest(lk), 'high_saved_mask_sha256': ev.digest(hk),
                     'high_reference_sha256': ev.digest(high_manifest.parent / 'images' / b['name']),
                     'low': results[0], 'high': results[1]})
        # Full native pixels, no resampling: a center crop of each held-out image.
        crop = np.concatenate((high_src[256:768,512:1536], pred1[256:768,512:1536]), axis=1)
        cv2.rectangle(crop, (0, 0), (2047, 28), (0,0,0), -1)
        cv2.putText(crop, a['name'] + '  source left / 2048 render right', (6,20), cv2.FONT_HERSHEY_SIMPLEX, .55, (255,255,255), 1, cv2.LINE_AA)
        tiles.append(crop)
    summary = {}
    for arm in ('low', 'high'):
        summary[arm] = {'mean_psnr_db': float(np.mean([r[arm]['spherical']['weighted_psnr_db'] for r in rows])),
                        'mean_ssim': float(np.mean([r[arm]['spherical_ssim'] for r in rows]))}
    report = {'method': 'Same source pixels and mask at 1024x512; high render downsampled 2x by area; no alignment. Held-out from splat training only, not SfM.',
              'manifests': {'low_sha256': ev.digest(low_manifest), 'high_sha256': ev.digest(high_manifest)},
              'evaluator_sha256': ev.digest(Path(__file__)),
              'run_artifacts': {arm: {'config_sha256': ev.digest(run / 'config.json'),
                                      'checkpoint_sha256': ev.digest(run / 'step-000003000.ckpt' / 'splat.ply')}
                                for arm, run in (('low', low_run), ('high', high_run))},
              'checkpoint_note': 'Saved render hashes are recorded; their association with the checkpoint is not independently proven.',
              'summary': summary, 'frames': rows}
    encoded = cv2.imencode('.png', np.concatenate(tiles, axis=0))[1].tobytes()
    if len(encoded) > 20 * 1024**2:
        raise RuntimeError('Contact sheet exceeds budget')
    with output.open('x') as f:
        json.dump(report, f, indent=2, allow_nan=False); f.write('\n')
    with sheet.open('xb') as f:
        f.write(encoded)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('low_manifest','low_run','high_manifest','high_run','output','sheet'):
        p.add_argument(name, type=Path)
    a = p.parse_args(); print(json.dumps(evaluate(a.low_manifest,a.low_run,a.high_manifest,a.high_run,a.output,a.sheet)['summary'], indent=2))


if __name__ == '__main__':
    main()
