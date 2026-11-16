#!/usr/bin/env python3
"""GPU diagnostic for separated lens centers projected onto an explicit sphere.

This is a finite-stitching-distance experiment, not estimated scene depth. Input
panoramas are independent observations of the two physical lenses. Their native
ERP layout is preserved; no perspective/cube-face cameras are extracted.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil

import cv2
import numpy as np
from scipy.spatial.transform import Rotation
import torch
import torch.nn.functional as F


def source_rays(directions, baseline, radius, rotation):
    """Return nominal lens rays for a sphere centered between the lens centers."""
    if radius <= np.linalg.norm(baseline) / 2:
        raise ValueError('Sphere must enclose both lens centers')
    offset = 0 if np.isinf(radius) else .5 / radius
    first = directions + baseline * offset
    second = directions - baseline * offset
    first = first / np.linalg.norm(first, axis=-1, keepdims=True)
    second = second / np.linalg.norm(second, axis=-1, keepdims=True)
    return first, second @ rotation


def sample_erp(image, mask, directions, device):
    """GPU bilinear sample with wrapped longitude and full-footprint validity."""
    h, w = mask.shape
    rays = torch.as_tensor(directions, dtype=torch.float32, device=device)
    longitude = torch.remainder(torch.atan2(-rays[..., 1], rays[..., 0]), 2 * torch.pi)
    x = longitude * w / (2 * torch.pi) - .5
    y = torch.acos(rays[..., 2].clamp(-1, 1)) * h / torch.pi - .5
    # Two extra columns permit interpolation across the ERP wrap, never the poles.
    grid = torch.stack((2 * (x + 1.5) / (w + 2) - 1, 2 * (y + .5) / h - 1), -1)[None]
    pixels = torch.as_tensor(image, device=device, dtype=torch.float32).permute(2, 0, 1)[None]
    valid = torch.as_tensor(mask > 127, device=device, dtype=torch.float32)[None, None]
    def sample(tensor):
        padded = torch.cat((tensor[..., -1:], tensor, tensor[..., :1]), -1)
        return F.grid_sample(padded, grid, mode='bilinear', padding_mode='zeros', align_corners=False)
    rgb = sample(pixels)[0].permute(1, 2, 0)
    support = (sample(valid)[0, 0] >= 1 - 1e-6) & (y >= 0) & (y <= h - 1)
    return rgb.round().clamp(0, 255).byte().cpu().numpy(), support.cpu().numpy(), torch.stack((x, y), -1).cpu().numpy()


def erp_directions(width, height):
    longitude = (np.arange(width) + .5) * 2 * np.pi / width
    latitude = np.pi / 2 - (np.arange(height) + .5) * np.pi / height
    return np.stack(np.broadcast_arrays(np.cos(latitude)[:, None] * np.cos(longitude)[None], -np.cos(latitude)[:, None] * np.sin(longitude)[None], np.sin(latitude)[:, None]), -1)


def sha(file):
    return hashlib.sha256(Path(file).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('rig', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--frames', type=int, nargs='+', required=True)
    parser.add_argument('--radii', type=float, nargs='+', default=[float('inf'), 20., 40., 80.])
    parser.add_argument('--orientation', type=Path, help='Matching full recording fused frame CSV')
    parser.add_argument('--device', choices=['mps', 'cpu'], default='mps')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output must be new')
    if shutil.disk_usage(args.output.parent).free < 36 * 1024**3:
        parser.error('Need 35 GiB reserve plus 1 GiB test budget')
    if args.device == 'mps' and not torch.backends.mps.is_available():
        parser.error('Apple GPU is unavailable')
    manifest = json.loads(args.manifest.read_text())
    rig = json.loads(args.rig.read_text())
    baseline = np.asarray(rig['baseline_direction'], dtype=float)
    baseline /= np.linalg.norm(baseline)
    rotation = np.asarray(rig['rotation_matrix'], dtype=float)
    poses = {}
    if args.orientation:
        with args.orientation.open() as stream:
            poses = {int(row['frame']): row for row in csv.DictReader(stream)}
    args.output.mkdir()
    reports = []
    for frame in args.frames:
        row, = [item for item in manifest['frames'] if item['frame'] == frame]
        paths = {key: args.manifest.parent / row[key] for key in ('lens0', 'lens1', 'mask0', 'mask1')}
        for key, file in paths.items():
            if key + '_sha256' in row and sha(file) != row[key + '_sha256']:
                raise ValueError('Input hash mismatch: ' + key)
        images = [cv2.imread(str(paths[key])) for key in ('lens0', 'lens1')]
        masks = [cv2.imread(str(paths[key]), 0) for key in ('mask0', 'mask1')]
        if any(item is None for item in images + masks):
            raise ValueError('Cannot read input')
        h, w = masks[0].shape
        if w != 2*h or any(im.shape[:2] != (h, w) for im in images + masks):
            raise ValueError('Expected matched full ERP input dimensions')
        directions = erp_directions(w, h)
        if poses:
            pose = poses[frame]
            q = [float(pose[key]) for key in ('q_x', 'q_y', 'q_z', 'q_w')]
            level_to_body = Rotation.from_quat(q).as_matrix().T @ Rotation.from_euler('z', float(pose['heading_rad'])).as_matrix()
            directions = directions @ level_to_body.T
        for radius in args.radii:
            first, second = source_rays(directions, baseline, radius, rotation)
            with torch.no_grad():
                rgb0, support0, xy0 = sample_erp(images[0], masks[0], first, args.device)
                rgb1, support1, xy1 = sample_erp(images[1], masks[1], second, args.device)
            prefer1 = np.einsum('...i,i->...', directions, baseline) >= 0
            use1 = support1 & (prefer1 | ~support0)
            use0 = support0 & ~use1
            output = np.zeros_like(rgb0)
            output[use0] = rgb0[use0]
            output[use1] = rgb1[use1]
            owner = np.where(use0, 1, np.where(use1, 2, 0)).astype(np.uint8)
            label = 'infinity' if np.isinf(radius) else f'radius-{radius:g}'
            folder = args.output / label
            folder.mkdir(exist_ok=True)
            stem = f'frame_{frame:08d}'
            cv2.imwrite(str(folder / (stem + '.png')), output)
            cv2.imwrite(str(folder / (stem + '-support.png')), (owner > 0).astype(np.uint8) * 255)
            # Both lens observations remain available for visual checking of the overlap.
            overlap = support0 & support1
            difference = np.zeros_like(rgb0)
            difference[overlap] = cv2.absdiff(rgb0, rgb1)[overlap]
            cv2.imwrite(str(folder / (stem + '-overlap-difference.png')), difference)
            np.savez_compressed(folder / (stem + '-provenance.npz'), source_xy=np.where(use1[..., None], xy1, xy0), source_lens=owner, origins=np.stack((-.5*baseline, .5*baseline)), lens1_rotation=rotation)
            report = {'frame': frame, 'radius_baselines': None if np.isinf(radius) else radius, 'color': str(folder / (stem + '.png')), 'supported_pixels': int((owner > 0).sum()), 'overlap_pixels': int(overlap.sum()), 'missing_pixels': int((owner == 0).sum()), 'rgb_overlap_mae': float(np.abs(rgb0.astype(float)-rgb1.astype(float))[overlap].mean()) if overlap.any() else None}
            reports.append(report)
            print(json.dumps(report), flush=True)
    result = {'method': 'two separated centers; explicit common sphere; no blend, flow or inpainting', 'device': args.device, 'baseline_length': 1, 'units': 'baseline units; no metric scale claimed', 'support_meaning': 'full source interpolation footprint only; not proof of correct depth or visibility', 'distance_assumption': 'sphere, not measured scene; do not promote to SfM as calibrated scene geometry', 'gap': 'only absent source support; no arbitrary seam margin', 'manifest_sha256': sha(args.manifest), 'rig_sha256': sha(args.rig), 'orientation_sha256': sha(args.orientation) if args.orientation else None, 'frames': reports}
    (args.output / 'manifest.json').write_text(json.dumps(result, indent=2)+'\n')


if __name__ == '__main__':
    main()
