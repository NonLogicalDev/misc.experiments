#!/usr/bin/env python3
"""Prepare a display-only perspective reference from an ERP capture and its COLMAP pose."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path

import cv2
import numpy as np
import compare_rigs
from temporal_depth_roi import rays


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def camera_basis(x, y, width, height):
    forward = rays(x, y, width, height)
    lon = (x / width - .5) * 2 * np.pi
    right = np.array([np.cos(lon), 0., -np.sin(lon)])
    return np.column_stack((right, np.cross(forward, right), forward))


def project_view(image, mask, aim, size, fov):
    height, width = mask.shape
    if image.shape != (height, width, 3) or width != 2 * height:
        raise ValueError('Expected a matching 2:1 ERP image and mask')
    if size <= 0 or not 0 < fov < 180 or not (0 <= aim[0] < width and 0 <= aim[1] < height):
        raise ValueError('Invalid size, FOV, or ERP aim')
    basis = camera_basis(*aim, width, height)
    focal = (size / 2) / math.tan(math.radians(fov) / 2)
    yy, xx = np.mgrid[:size, :size]
    directions = np.stack(((xx + .5 - size / 2) / focal,
                           (yy + .5 - size / 2) / focal,
                           np.ones_like(xx)), axis=-1) @ basis.T
    u = (np.arctan2(directions[..., 0], directions[..., 2]) * width / (2 * np.pi) + width / 2 - .5) % width
    v = np.arctan2(directions[..., 1], np.hypot(directions[..., 0], directions[..., 2])) * height / np.pi + height / 2 - .5
    ix = np.floor(u).astype(int)
    iy = np.floor(v).astype(int)
    inside = (iy >= 0) & (iy + 1 < height)
    y0 = np.clip(iy, 0, height - 1)
    y1 = np.clip(iy + 1, 0, height - 1)
    x1 = (ix + 1) % width
    valid = inside & (mask[y0, ix] == 255) & (mask[y0, x1] == 255) & (mask[y1, ix] == 255) & (mask[y1, x1] == 255)
    result = cv2.remap(image, u.astype('float32'), v.astype('float32'), cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)
    result[~valid] = 0
    return result, valid, basis, focal


def prepare(image_path, mask_path, images_txt, image_name, ply, expected_sha, seed, aim, size, fov, out):
    image_path, mask_path, images_txt, ply, seed, out = map(Path, (image_path, mask_path, images_txt, ply, seed, out))
    if sha(ply) != expected_sha.lower():
        raise ValueError('PLY SHA-256 mismatch')
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
    if image is None or mask is None:
        raise ValueError('Cannot read source image or mask')
    rows = [line.split() for line in images_txt.read_text().splitlines() if len(line.split()) == 10 and line.split()[-1] == image_name]
    if len(rows) != 1:
        raise ValueError('Expected one named COLMAP camera pose')
    row = rows[0]
    q = np.asarray(list(map(float, row[1:5])))
    if not np.isfinite(q).all() or abs(np.linalg.norm(q) - 1) > 1e-5:
        raise ValueError('Expected a finite unit quaternion')
    rotation = compare_rigs.rotation(q)
    translation = np.asarray(list(map(float, row[5:8])))
    if not np.isfinite(translation).all():
        raise ValueError('Invalid translation')
    center = -rotation.T @ translation
    view, valid, basis, focal = project_view(image, mask, aim, size, fov)
    world_from_cv = rotation.T @ basis
    camera_from_world = world_from_cv.T
    view_t = -camera_from_world @ center
    rv, _ = cv2.Rodrigues(camera_from_world)
    angle = np.linalg.norm(rv)
    axis = rv.reshape(3) / angle if angle else np.zeros(3)
    quat = [math.cos(angle / 2), *(axis * math.sin(angle / 2))]
    c2w = np.eye(4)
    c2w[:3, :3] = world_from_cv @ np.diag([1, -1, -1])
    c2w[:3, 3] = center
    out.mkdir(exist_ok=False)
    data = out / 'data'
    (data / 'images').mkdir(parents=True)
    (data / 'masks').mkdir()
    (data / 'sparse/0').mkdir(parents=True)
    source = data / 'images/eval_000001_cam0.png'
    support = data / 'masks/eval_000001_cam0.png'
    if not cv2.imwrite(str(source), view) or not cv2.imwrite(str(support), valid.astype('uint8') * 255):
        raise OSError('Cannot write perspective source or mask')
    os.link(source, data / 'images/train_000001_cam0.png')
    os.link(support, data / 'masks/train_000001_cam0.png')
    os.link(seed, data / 'seed.ply')
    (data / 'sparse/0/cameras.txt').write_text(f'1 PINHOLE {size} {size} {focal:.17g} {focal:.17g} {size/2:g} {size/2:g}\n')
    pose = ' '.join(map(str, quat + list(view_t)))
    (data / 'sparse/0/images.txt').write_text(f'1 {pose} 1 train_000001_cam0.png\n\n2 {pose} 1 eval_000001_cam0.png\n\n')
    (data / 'sparse/0/points3D.txt').write_text('# PLY seed\n')
    case = {'source_image': str(image_path), 'source_sha256': sha(image_path), 'source_mask_sha256': sha(mask_path), 'source_pose': row,
            'erp_target_pixel_center_xy': list(aim), 'resolution': [size, size], 'fov_y_degrees': fov, 'focal_px': focal,
            'principal_point': [size/2, size/2], 'c2w_opengl_row_major': c2w.tolist(), 'world_from_camera_cv': world_from_cv.tolist(),
            'camera_center_world': center.tolist(), 'camera_from_world_cv': camera_from_world.tolist(), 'translation_camera': view_t.tolist(),
            'ply': str(ply), 'ply_sha256': expected_sha.lower(), 'seed_sha256': sha(seed), 'primitive': '3dgs', 'sh_degree': 3,
            'background_rgb': [0, 0, 0], 'scene_transform': 'identity', 'reference_source_image': str(source),
            'reference_valid_mask': str(support), 'valid_fraction': float(valid.mean()),
            'interpolation': 'ERP pixel centers, bilinear RGB, longitude periodic, all four source-mask taps valid',
            'pixel_convention': 'perspective pixel centers x+0.5,y+0.5; CV right/down/forward; OpenGL right/up/back',
            'color': 'original decoded sRGB bytes; no gamma correction in interpolation'}
    (out / 'case.json').write_text(json.dumps(case, indent=2) + '\n')
    return case


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('image', 'mask', 'images-txt', 'image-name', 'ply', 'ply-sha256', 'seed', 'out'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--aim', type=float, nargs=2, required=True, metavar=('X_CENTER', 'Y_CENTER'))
    parser.add_argument('--size', type=int, default=512)
    parser.add_argument('--fov-y', type=float, default=55)
    args = parser.parse_args()
    prepare(args.image, args.mask, args.images_txt, args.image_name, args.ply, args.ply_sha256, args.seed, args.aim, args.size, args.fov_y, args.out)


if __name__ == '__main__':
    main()
