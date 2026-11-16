#!/usr/bin/env python3
"""Measure aligned render/reference ERP pairs using masks and spherical area."""
import argparse
import json
import math
from pathlib import Path

import cv2
import numpy as np


def load_image(path, grayscale=False):
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE if grayscale else cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f'Cannot read {path}')
    return image


def frame_metrics(reference, rendered, mask):
    if reference.dtype != np.uint8 or rendered.dtype != np.uint8 or mask.dtype != np.uint8:
        raise ValueError('Inputs must be 8-bit images')
    if reference.shape != rendered.shape or reference.ndim != 3 or reference.shape[2] != 3:
        raise ValueError('Reference and render must have identical RGB dimensions')
    height, width = reference.shape[:2]
    if width != 2 * height or mask.shape != (height, width):
        raise ValueError('Inputs must be 2:1 equirectangular images with a matching mask')
    keep = mask >= 128
    if not np.any(keep):
        raise ValueError('Mask contains no valid pixels')
    ref = reference.astype(np.float64) / 255.0
    pred = rendered.astype(np.float64) / 255.0
    abs_error = np.abs(ref - pred).mean(axis=2)
    sq_error = ((ref - pred) ** 2).mean(axis=2)
    lat = 90.0 - 180.0 * (np.arange(height) + 0.5) / height
    row_area = np.cos(np.deg2rad(lat))[:, None]

    # Centered differences wrap horizontally and require valid neighbors vertically.
    valid_grad = keep & np.roll(keep, 1, axis=1) & np.roll(keep, -1, axis=1)
    valid_grad[1:] &= keep[:-1]
    valid_grad[:-1] &= keep[1:]
    valid_grad[[0, -1], :] = False
    def gradient(rgb):
        gray = 0.114 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.299 * rgb[..., 2]
        gx = (np.roll(gray, -1, axis=1) - np.roll(gray, 1, axis=1)) * 0.5
        gy = (np.roll(gray, -1, axis=0) - np.roll(gray, 1, axis=0)) * 0.5
        return np.hypot(gx, gy)
    grad_ref, grad_pred = gradient(ref), gradient(pred)

    def summarize(region):
        selected = keep & region
        count = int(selected.sum())
        if not count:
            return None
        weights = selected * row_area
        denominator = float(weights.sum())
        mse = float((sq_error * weights).sum() / denominator)
        gm = valid_grad & region
        gw = gm * row_area
        if np.any(gm):
            gden = float(gw.sum())
            rg = float((grad_ref * gw).sum() / gden)
            pg = float((grad_pred * gw).sum() / gden)
            ratio = pg / rg if rg > 1e-12 else None
        else:
            rg = pg = ratio = None
        return {'valid_pixels': count, 'weighted_mse': mse,
                'weighted_psnr_db': -10.0 * math.log10(mse) if mse else None,
                'weighted_mae': float((abs_error * weights).sum() / denominator),
                'gradient_valid_pixels': int(gm.sum()),
                'reference_gradient': rg, 'render_gradient': pg, 'gradient_ratio': ratio}
    mse = float(sq_error[keep].mean())
    result = {'valid_fraction': float(keep.mean()),
              'pixel_psnr_db': -10.0 * math.log10(mse) if mse else None,
              'spherical': summarize(np.ones_like(keep, dtype=bool)), 'latitude_bands': {}}
    for low in (-90, -60, -30, 0, 30, 60):
        region = np.broadcast_to((lat >= low)[:, None] & (lat < low + 30)[:, None], keep.shape)
        result['latitude_bands'][f'{low}..{low + 30}'] = summarize(region)
    return result


def evaluate(directory):
    references = sorted(directory.glob('eval-gt-*.png'))
    if not references:
        raise ValueError(f'No eval-gt-*.png images in {directory}')
    rows = []
    for path in references:
        suffix = path.name[len('eval-gt-'):]
        rendered, mask = directory / f'eval-render-{suffix}', directory / f'eval-mask-{suffix}'
        values = frame_metrics(load_image(path), load_image(rendered), load_image(mask, grayscale=True))
        rows.append({'id': suffix.removesuffix('.png'), **values})
    finite_psnr = [row['spherical']['weighted_psnr_db'] for row in rows if row['spherical']['weighted_psnr_db'] is not None]
    ratios = [row['spherical']['gradient_ratio'] for row in rows if row['spherical']['gradient_ratio'] is not None]
    return {'method': 'masked ERP area-weighted RGB error and grayscale gradient magnitude; unaligned 8-bit images; null PSNR means exact match',
            'frames': rows, 'summary': {'frames': len(rows),
            'mean_finite_spherical_psnr_db': float(np.mean(finite_psnr)) if finite_psnr else None,
            'perfect_spherical_frames': len(rows) - len(finite_psnr),
            'mean_finite_pixel_psnr_db': float(np.mean([row['pixel_psnr_db'] for row in rows if row['pixel_psnr_db'] is not None])) if any(row['pixel_psnr_db'] is not None for row in rows) else None,
            'perfect_pixel_frames': sum(row['pixel_psnr_db'] is None for row in rows),
            'mean_gradient_ratio': float(np.mean(ratios)) if ratios else None}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('evaluation', type=Path)
    parser.add_argument('--output', type=Path, help='write a new JSON file; default stdout')
    args = parser.parse_args()
    result = evaluate(args.evaluation)
    text = json.dumps(result, indent=2, allow_nan=False) + '\n'
    if args.output:
        with args.output.open('x') as f: f.write(text)
    else:
        print(text, end='')


if __name__ == '__main__':
    main()
