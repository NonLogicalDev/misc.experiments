#!/usr/bin/env python3
"""Audit a zero-step higher-resolution resume against its original render."""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np
import compare_splat_pixels as pixels


def audit(low_data, low_run, high_data, high_run):
    low_manifest = json.loads((low_data / 'manifest.json').read_text())
    high_manifest = json.loads((high_data / 'manifest.json').read_text())
    names = low_manifest['heldout_evaluation_order']
    if len(names) != 36 or names != high_manifest['heldout_evaluation_order'] or len(set(names)) != len(names):
        raise ValueError('Held-out inventory or order differs')
    low_rows = {r['name']: r for r in low_manifest['frames']}
    high_rows = {r['name']: r for r in high_manifest['frames']}
    pose_low = low_data / 'sparse/0/images.txt'; pose_high = high_data / 'sparse/0/images.txt'
    if pixels.sha(pose_low) != pixels.sha(pose_high): raise ValueError('Pose rows differ')
    lc = json.loads((low_run / 'config.json').read_text()); hc = json.loads((high_run / 'config.json').read_text())
    if Path(lc['data']).resolve() != low_data.resolve() or Path(hc['data']).resolve() != high_data.resolve(): raise ValueError('Config data mismatch')
    diff = {k: [lc.get(k), hc.get(k)] for k in set(lc) | set(hc) if lc.get(k) != hc.get(k)}
    allowed = {'data', 'output_dir_prefix', 'output_dir_name', 'resume', 'steps_per_save', 'refine_stop_iter', 'refine_stop_num_iter'}
    if set(diff) - allowed: raise ValueError(f'Unexpected config differences: {diff}')
    rows = []; differences = []; squared = weighted_absolute = weighted_squared = area = 0.0; channels = 0; max_difference = 0
    for i, name in enumerate(names):
        a, b = low_rows[name], high_rows[name]
        for key in ('source_name', 'source_frame', 'lens', 'timestamp_microseconds', 'source_packet_pts'):
            if a[key] != b[key]: raise ValueError(f'Source identity differs: {name} {key}')
        lr = pixels.load(low_run / f'eval-render-{i:05d}.png'); hr = pixels.load(high_run / f'eval-render-{i:05d}.png')
        lg = pixels.load(low_run / f'eval-gt-{i:05d}.png'); hg = pixels.load(high_run / f'eval-gt-{i:05d}.png')
        lm = pixels.load(low_run / f'eval-mask-{i:05d}.png', True); hm = pixels.load(high_run / f'eval-mask-{i:05d}.png', True)
        if lr.shape != (512, 1024, 3) or hr.shape != (1024, 2048, 3) or lg.shape != lr.shape or hg.shape != hr.shape or lm.shape != lr.shape[:2] or hm.shape != hr.shape[:2]: raise ValueError(f'Unexpected render dimensions: {name}')
        for gt, mask, data in ((lg, lm, low_data), (hg, hm, high_data)):
            actual = pixels.load(data / 'images' / name); expected_mask = pixels.load(data / 'masks' / name, True)
            if not np.array_equal(mask, expected_mask) or np.max(np.abs(gt.astype(np.int16) - actual.astype(np.int16))) > 1: raise ValueError(f'Saved reference or mask differs: {name}')
        rows.append(pixels.score(hg, hr, hr, hm, hm))
        reduced = cv2.resize(hr, (1024, 512), interpolation=cv2.INTER_AREA)
        conservative = (hm.reshape(512, 2, 1024, 2) >= 128).all(axis=(1, 3))
        keep = conservative & (lm >= 128)
        if not keep.any(): raise ValueError(f'No common valid pixels: {name}')
        delta = np.abs(reduced.astype(np.int16) - lr.astype(np.int16)).astype(np.float64) / 255.0
        weights = keep * np.cos((np.arange(512) + .5 - 256) * np.pi / 512)[:, None]
        per_pixel = delta.mean(axis=2); sq = (delta * delta).mean(axis=2)
        area += float(weights.sum()); weighted_absolute += float((per_pixel * weights).sum()); weighted_squared += float((sq * weights).sum())
        count = int(keep.sum()); channels += 3 * count; squared += float((delta[keep] ** 2).sum())
        largest = int(np.max(np.abs(reduced.astype(np.int16) - lr.astype(np.int16))[keep])); max_difference = max(max_difference, largest)
        differences.append({'name': name, 'common_pixels': count, 'mean_absolute_difference_0_255': float(delta[keep].mean() * 255), 'max_channel_difference_0_255': largest})
    pooled = pixels.pool(rows)
    return {'method': 'No image alignment. High-resolution error uses saved RGB ground truth and mask. Render difference compares the 2048 render area-reduced to 1024 against the original 1024 render on their common conservative mask; sampling and rasterization can differ even with identical geometry.', 'config_differences': diff, 'pose_sha256': pixels.sha(pose_low), 'low_manifest_sha256': pixels.sha(low_data / 'manifest.json'), 'high_manifest_sha256': pixels.sha(high_data / 'manifest.json'), 'high_resolution': {'frames': pooled['frames'], 'valid_pixels': pooled['common_valid_pixels'], 'spherical_area': pooled['common_spherical_area'], **pooled['baseline']}, 'render_difference': {'frames': len(differences), 'common_pixels': channels // 3, 'weighted_mean_absolute_difference_0_255': 255 * weighted_absolute / area, 'weighted_rmse_0_255': 255 * (weighted_squared / area) ** .5, 'pixel_rmse_0_255': 255 * (squared / channels) ** .5, 'max_channel_difference_0_255': max_difference, 'per_frame': differences}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('low_data', 'low_run', 'high_data', 'high_run', 'output'): parser.add_argument(name, type=Path)
    a = parser.parse_args()
    report = audit(a.low_data, a.low_run, a.high_data, a.high_run)
    with a.output.open('x') as f: json.dump(report, f, indent=2, allow_nan=False); f.write('\n')
    print(json.dumps({k: report[k] for k in ('config_differences', 'high_resolution', 'render_difference')}, indent=2))


if __name__ == '__main__': main()
