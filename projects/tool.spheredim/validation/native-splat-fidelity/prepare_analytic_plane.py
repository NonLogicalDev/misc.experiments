#!/usr/bin/env python3
"""Generate a deterministic analytic plane observed by full ERP cameras."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import cv2
import numpy as np
W, H = (768, 384)
PLANE_Z = 3.0
XMIN, XMAX = (-1.8, 1.8)
YMIN, YMAX = (-1.4, 1.4)
CELL = 0.16
CAMERAS = [(-0.24, -0.04, -0.12), (0.0, 0.02, 0.0), (0.24, -0.03, 0.12), (-0.12, 0.05, 0.06), (0.13, 0.04, -0.06)]

def chart(x, y):
    ix = np.floor((x - XMIN) / CELL).astype(int)
    iy = np.floor((y - YMIN) / CELL).astype(int)
    code = (ix * 73 + iy * 151 + ix * iy * 17) % 251
    base = np.where((ix + iy) % 2 == 0, 220, 35)
    return np.stack((base, (code * 3 + 30) % 256, (code * 7 + 50) % 256), axis=-1).astype(np.uint8)

def camera(cx, cy, yaw):
    c, s = (math.cos(yaw), math.sin(yaw))
    r = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])
    center = np.array([cx, cy, 0.0])
    return (r, center, -r @ center)

def render(r, center):
    yy, xx = np.mgrid[:H, :W]
    lon = (xx + 0.5 - W / 2) * 2 * np.pi / W
    lat = (yy + 0.5 - H / 2) * np.pi / H
    dc = np.stack([np.cos(lat) * np.sin(lon), np.sin(lat), np.cos(lat) * np.cos(lon)], axis=-1)
    dw = dc @ r
    den = dw[..., 2]
    distance = np.divide(PLANE_Z - center[2], den, out=np.zeros_like(den), where=np.abs(den) > 1e-12)
    x = center[0] + distance * dw[..., 0]
    y = center[1] + distance * dw[..., 1]
    valid = (distance > 0) & (x >= XMIN) & (x < XMAX) & (y >= YMIN) & (y < YMAX)
    rgb = np.zeros((H, W, 3), np.uint8)
    rgb[valid] = chart(x[valid], y[valid])
    return (rgb, valid, dc, dw, distance)

def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(1048576), b''):
            h.update(b)
    return h.hexdigest()

def prepare(out):
    out = Path(out)
    out.mkdir(exist_ok=False)
    (out / 'images').mkdir()
    (out / 'masks').mkdir()
    (out / 'sparse/0').mkdir(parents=True)
    (out / 'sparse/0/cameras.txt').write_text(f'1 EQUIRECTANGULAR {W} {H} {W} {H}\n')
    (out / 'sparse/0/points3D.txt').write_text('# Exact plane seed supplied as PLY\n')
    rows = []
    frames = []
    for i, (cx, cy, yaw) in enumerate(CAMERAS):
        r, center, t = camera(cx, cy, yaw)
        rgb, valid, dc, dw, distance = render(r, center)
        assert np.allclose(r @ r.T, np.eye(3), atol=1e-12) and np.linalg.det(r) > 0.999999
        assert np.allclose(np.linalg.norm(dc, axis=-1), 1, atol=1e-12)
        assert np.max(np.abs(center[2] + distance[valid] * dw[..., 2][valid] - PLANE_Z)) < 1e-12
        assert valid.any() and np.all(distance[valid] > 0)
        name = ('train' if i < 3 else 'eval') + f'_{i:06}_cam0.png'
        cv2.imwrite(str(out / 'images' / name), rgb[..., ::-1])
        cv2.imwrite(str(out / 'masks' / name), valid.astype(np.uint8) * 255)
        q = [math.cos(yaw / 2), 0, math.sin(yaw / 2), 0]
        rows.extend([f'{i + 1} ' + ' '.join(map(str, q + list(t))) + f' 1 {name}', ''])
        frames.append({'name': name, 'split': 'train' if i < 3 else 'eval', 'center': center.tolist(), 'yaw_rad': yaw, 'valid_pixels': int(valid.sum()), 'image_sha256': digest(out / 'images' / name), 'mask_sha256': digest(out / 'masks' / name)})
    (out / 'sparse/0/images.txt').write_text('\n'.join(rows) + '\n')
    xs = np.linspace(XMIN + 0.02, XMAX - 0.02, 90)
    ys = np.linspace(YMIN + 0.02, YMAX - 0.02, 70)
    xx, yy = np.meshgrid(xs, ys)
    colors = chart(xx, yy)
    seed = out / 'seed.ply'
    with seed.open('w') as f:
        f.write(f'ply\nformat ascii 1.0\nelement vertex {xx.size}\nproperty float x\nproperty float y\nproperty float z\nproperty uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n')
        for x, y, col in zip(xx.flat, yy.flat, colors.reshape(-1, 3)):
            f.write(f'{x:.9g} {y:.9g} {PLANE_Z:g} {int(col[0])} {int(col[1])} {int(col[2])}\n')
    report = {'description': 'Analytic sharp textured plane with known ERP cameras; synthetic pipeline fidelity diagnostic only.', 'width': W, 'height': H, 'plane_z': PLANE_Z, 'plane_bounds': [XMIN, XMAX, YMIN, YMAX], 'chart_cell_world': CELL, 'seed_points': int(xx.size), 'seed_sha256': digest(seed), 'frames': frames, 'checks': ['proper rotations', 'unit native ERP pixel-center rays', 'positive forward plane intersection and exact plane Z', 'source RGB and masks generated from same analytic ray intersection'], 'fine_pattern_note': 'Cell spacing must be measured in projected pixels before GPU acceptance.'}
    (out / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n')
    return report
if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('output')
    a = p.parse_args()
    prepare(a.output)
