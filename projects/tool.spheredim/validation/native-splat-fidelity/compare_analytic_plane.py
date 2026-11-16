"""Compare held-out plane renders on the same source support."""
import argparse
import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np

import prepare_analytic_plane as plane


def load_image(path, flags=cv2.IMREAD_COLOR):
    image = cv2.imread(str(path), flags)
    if image is None:
        raise ValueError(f"Could not load image: {path}")
    return image


def load_frame(root, name, index):
    source = load_image(root / 'images' / name)
    if source.shape != (plane.H, plane.W, 3):
        raise ValueError(f"Invalid source dimensions for {name}: expected {plane.W}x{plane.H}")
    mask = load_image(root / 'masks' / name, cv2.IMREAD_GRAYSCALE) > 0
    if source.shape[:2] != mask.shape or not mask.any():
        raise ValueError(f"Invalid source mask for {name}: empty or wrong dimensions")
    renders = []
    for phase in ('zero', 'fit'):
        phase_mask = load_image(root / phase / f'eval-mask-{index:05}.png', cv2.IMREAD_GRAYSCALE) > 0
        if not np.array_equal(mask, phase_mask):
            raise ValueError(f"{phase} mask differs from source mask for {name}")
        ground_truth = load_image(root / phase / f'eval-gt-{index:05}.png')
        if ground_truth.shape != source.shape or np.max(np.abs(source.astype('int16') - ground_truth.astype('int16'))) > 1:
            raise ValueError(f"{phase} ground truth differs from source for {name}")
        render = load_image(root / phase / f'eval-render-{index:05}.png')
        if render.shape != source.shape:
            raise ValueError(f"{phase} render dimensions differ from source for {name}")
        renders.append(render)
    return source, mask, renders


def score(source, render, mask):
    safe = cv2.erode(mask.astype('uint8'), np.ones((11, 11), np.uint8)) > 0
    if not safe.any():
        raise ValueError('Mask has no interior pixels for SSIM')
    a = source.astype('float64') / 255
    b = render.astype('float64') / 255
    mse = float(np.mean((a[mask] - b[mask]) ** 2))
    def gaussian(x):
        return cv2.GaussianBlur(x, (11, 11), 1.5)
    ma, mb = gaussian(a), gaussian(b)
    va, vb = gaussian(a * a) - ma * ma, gaussian(b * b) - mb * mb
    cov = gaussian(a * b) - ma * mb
    ssim = ((2 * ma * mb + .01**2) * (2 * cov + .03**2)) / ((ma * ma + mb * mb + .01**2) * (va + vb + .03**2))
    return {'valid_mse': mse, 'valid_psnr': -10 * math.log10(mse) if mse else None, 'interior_ssim': float(ssim[safe].mean()), 'ssim_interior_pixels': int(safe.sum())}


def cell_contrast(source, zero, fit, mask, camera_index):
    rotation, center, _ = plane.camera(*plane.CAMERAS[camera_index])
    _, _, _, world_rays, distance = plane.render(rotation, center)
    xx = center[0] + distance * world_rays[..., 0]
    yy = center[1] + distance * world_rays[..., 1]
    ix = np.floor((xx - plane.XMIN) / plane.CELL).astype(int)
    iy = np.floor((yy - plane.YMIN) / plane.CELL).astype(int)
    grays = [cv2.cvtColor(x, cv2.COLOR_BGR2GRAY).astype(float) / 255 for x in (source, zero, fit)]
    cells = {}
    for x, y in zip(ix[mask], iy[mask]):
        cells[(int(x), int(y))] = None
    for key in cells:
        selected = mask & (ix == key[0]) & (iy == key[1])
        if int(selected.sum()) >= 4:
            cells[key] = [float(a[selected].mean()) for a in grays]
    pairs = []
    for (x, y), values in cells.items():
        if values is None:
            continue
        for neighbor in ((x + 1, y), (x, y + 1)):
            other = cells.get(neighbor)
            if other is not None:
                pairs.append([values[j] - other[j] for j in range(3)])
    pairs = np.asarray(pairs)
    if not len(pairs):
        raise ValueError('No adjacent chart cells with sufficient support')
    contrast = np.abs(pairs).mean(axis=0)
    return {'adjacent_cell_pairs': len(pairs), 'source_mean_abs_luma_difference': float(contrast[0]), 'zero_mean_abs_luma_difference': float(contrast[1]), 'fit_mean_abs_luma_difference': float(contrast[2]), 'zero_to_source_ratio': float(contrast[1] / contrast[0]), 'fit_to_source_ratio': float(contrast[2] / contrast[0]), 'fit_signed_contrast_mae': float(np.abs(pairs[:, 2] - pairs[:, 0]).mean())}


def compare(root):
    manifest = json.loads((root / 'manifest.json').read_text())
    results = {}
    for i, row in enumerate(manifest['frames'][3:]):
        name = row['name']
        source, mask, (zero, fit) = load_frame(root, name, i)
        ys, xs = np.where(mask)
        x0, x1 = max(0, xs.min() - 3), min(plane.W, xs.max() + 4)
        y0, y1 = max(0, ys.min() - 3), min(plane.H, ys.max() + 4)
        panel = np.hstack([a[y0:y1, x0:x1] for a in (source, zero, fit)])
        crop = root / f'comparison-{i}.png'
        if not cv2.imwrite(str(crop), panel):
            raise OSError(f'Could not write image: {crop}')
        results[name] = {'valid_pixels': int(mask.sum()), 'zero': score(source, zero, mask), 'fit': score(source, fit, mask), 'cell_contrast': cell_contrast(source, zero, fit, mask, i + 3), 'crop': str(crop), 'crop_sha256': hashlib.sha256(crop.read_bytes()).hexdigest(), 'crop_xyxy': [int(x0), int(y0), int(x1), int(y1)]}
    report = {'method': 'Identical valid source plane support, unaligned sRGB RGB MSE; SSIM uses Gaussian 11x11 sigma1.5 and excludes mask-boundary neighborhoods. Contrast compares means of adjacent 0.16-unit world-chart cells with at least four valid pixels per cell. Crops: source, zero, fit.', 'frames': results}
    (root / 'comparison.json').write_text(json.dumps(report, indent=2, allow_nan=False))
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    args = parser.parse_args()
    print(json.dumps(compare(args.root)))


if __name__ == '__main__':
    main()
