#!/usr/bin/env python3
"""Compare the same selected training views in two completed raw audits."""
import argparse
import json
from pathlib import Path
import cv2
import numpy as np
import compare_splat_pixels as pixels

REGIONS = [('doorway', 930, (384, 256, 256, 256)), ('fabric', 1005, (512, 0, 256, 256)), ('window blinds', 1500, (640, 128, 256, 256))]


def compare(a, b, report_path, image_path):
    plans = [json.loads((x / 'plan.json').read_text()) for x in (a, b)]
    audits = [json.loads((x / 'audit.json').read_text()) for x in (a, b)]
    if any(x['control_count_exact'] != 26 for x in audits): raise ValueError('Expected 26 verified controls')
    if plans[0]['source'] != plans[1]['source'] or plans[0]['rename'] != plans[1]['rename'] or plans[0]['original_pose_sha256'] != plans[1]['original_pose_sha256']: raise ValueError('Source, pose, or mapping differs')
    source = Path(plans[0]['source']); names = sorted(x for x in plans[0]['rename'] if x.startswith('train_'))
    if len(names) != 10: raise ValueError('Expected 10 selected training views')
    rows = []; images = {}
    for name in names:
        ref = pixels.load(source / 'images' / name); mask = pixels.load(source / 'masks' / name, True); preds = []
        for folder, plan in zip((a, b), plans):
            order = sorted(p.name for p in (folder / 'data/images').iterdir() if p.name.startswith('eval_')); index = order.index(plan['rename'][name]); run = folder / 'render'
            gt = pixels.load(run / f'eval-gt-{index:05d}.png'); saved_mask = pixels.load(run / f'eval-mask-{index:05d}.png', True)
            if not np.array_equal(mask, saved_mask) or np.max(np.abs(ref.astype(np.int16) - gt.astype(np.int16))) > 1: raise ValueError(f'Reference or mask differs: {name}')
            preds.append(pixels.load(run / f'eval-render-{index:05d}.png'))
        row = pixels.score(ref, *preds, mask, mask); row['name'] = name; rows.append(row)
        if name in {f'train_{frame:06d}_cam0.png' for _, frame, _ in REGIONS}: images[name] = (ref, *preds)
    panels = []
    for label, frame, (x, y, w, h) in REGIONS:
        name = f'train_{frame:06d}_cam0.png'; ref, old, new = images[name]; sx, sy = ref.shape[1] / 1024, ref.shape[0] / 512
        if (sx, sy) != (2, 2): raise ValueError('Expected 2048 x 1024 source')
        x, y, w, h = (int(x * sx), int(y * sy), int(w * sx), int(h * sy))
        panels.append(np.concatenate([im[y:y+h, x:x+w] for im in (ref, old, new)], axis=1))
    mosaic = np.concatenate(panels, axis=0)
    if not cv2.imwrite(str(image_path), mosaic, [cv2.IMWRITE_JPEG_QUALITY, 92]): raise RuntimeError('Failed to write crops')
    report = {'method': 'Same 10 selected source captures and poses, common mask, no alignment or appearance correction. Crops use fixed 1024-coordinate regions scaled by two; columns source, baseline, candidate; rows doorway, fabric, blinds. JPEG is visual evidence, not the metric input.', 'audit_sha256': [pixels.sha(x / 'audit.json') for x in (a, b)], 'summary': pixels.pool(rows), 'frames': rows, 'crop_path': str(image_path), 'crop_sha256': pixels.sha(image_path)}
    with report_path.open('x') as f: json.dump(report, f, indent=2, allow_nan=False); f.write('\n')
    print(json.dumps(report['summary'], indent=2))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for n in ('baseline', 'candidate', 'report', 'crops'): p.add_argument(n, type=Path)
    a = p.parse_args(); compare(a.baseline, a.candidate, a.report, a.crops)


if __name__ == '__main__': main()
