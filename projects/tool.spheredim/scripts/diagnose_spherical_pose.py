#!/usr/bin/env python3
"""Diagnose pairwise bearing consistency on whole equirectangular frames.

The best-fit rotation is a diagnostic, not a pose correction. Translation,
parallax, changing masks and mismatched or moving features all affect it.
"""
import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def image_rays(points, width, height):
    if width != 2 * height:
        raise ValueError('Expected a 2:1 panorama')
    longitude = (points[:, 0] / width - 0.5) * (2.0 * np.pi)
    latitude_down = (points[:, 1] / height - 0.5) * np.pi
    return np.column_stack((np.cos(latitude_down) * np.sin(longitude),
                            np.sin(latitude_down),
                            np.cos(latitude_down) * np.cos(longitude)))


def angles_degrees(first, second):
    return np.degrees(np.arccos(np.clip(np.sum(first * second, axis=1), -1, 1)))


def best_rotation(first, second, trim=0.8, iterations=4):
    """Fit a rotation on source/target bearing vectors, trimming large residuals."""
    if first.shape != second.shape or first.ndim != 2 or first.shape[1] != 3 or len(first) < 8:
        raise ValueError('At least eight paired 3D bearings are required')
    keep = np.arange(len(first))
    for _ in range(iterations):
        u, _, vt = np.linalg.svd(first[keep].T @ second[keep])
        diag = np.diag([1., 1., np.linalg.det(vt.T @ u.T)])
        rotation = vt.T @ diag @ u.T
        errors = angles_degrees(first @ rotation.T, second)
        keep = np.argsort(errors)[:max(8, int(len(first) * trim))]
    return rotation


def epipolar_quality(first, second, baseline, minimum_parallax_degrees=0.5):
    """Angular distance from each camera baseline to the two-bearing plane."""
    baseline_length = float(np.linalg.norm(baseline))
    if baseline_length < 1e-12:
        return None
    normal = np.cross(first, second)
    length = np.linalg.norm(normal, axis=1)
    eligible = length > np.sin(np.deg2rad(minimum_parallax_degrees))
    if not np.any(eligible):
        return None
    sine = np.abs(normal[eligible] @ (baseline / baseline_length)) / length[eligible]
    errors = np.degrees(np.arcsin(np.clip(sine, 0, 1)))
    return {'eligible_matches': len(errors), 'minimum_bearing_parallax_degrees': minimum_parallax_degrees,
            'median_degrees': float(np.median(errors)), 'p90_degrees': float(np.percentile(errors, 90))}


def pose_quality(first, second, points, width, seed=3):
    if len(first) < 16:
        raise ValueError('At least 16 matches are required for a split diagnostic')
    ids = np.random.default_rng(seed).permutation(len(first))
    train, held = ids[::2], ids[1::2]
    rotation = best_rotation(first[train], second[train])
    before = angles_degrees(first[held], second[held])
    after = angles_degrees(first[held] @ rotation.T, second[held])
    sectors = np.floor(points[held, 0] * 8 / width).astype(int).clip(0, 7)
    per_sector = []
    for s in range(8):
        subset = sectors == s
        if np.any(subset):
            per_sector.append({'longitude_sector': s, 'matches': int(subset.sum()),
                               'before_median_degrees': float(np.median(before[subset])),
                               'after_median_degrees': float(np.median(after[subset]))})
    correction_angle = np.degrees(np.arccos(np.clip((np.trace(rotation) - 1) / 2, -1, 1)))
    return {'fit_matches': len(train), 'heldout_matches': len(held),
            'fitted_rotation_degrees': float(correction_angle),
            'heldout_before_median_degrees': float(np.median(before)),
            'heldout_before_p90_degrees': float(np.percentile(before, 90)),
            'heldout_after_median_degrees': float(np.median(after)),
            'heldout_after_p90_degrees': float(np.percentile(after, 90)),
            'heldout_longitude_sectors': per_sector}


def analyze(dataset, first_id, second_id, ratio):
    records = {frame['source_frame']: frame for frame in json.loads((dataset / 'manifest.json').read_text())['frames']}
    def read_frame(number):
        item = records[number]
        root = dataset / 'holdout' if item['split'] == 'heldout' else dataset
        image = cv2.imread(str(root / 'images' / item['file']), cv2.IMREAD_GRAYSCALE)
        mask = cv2.imread(str(root / 'masks' / item['file']), cv2.IMREAD_GRAYSCALE)
        pose = np.asarray(item['world_from_camera'], dtype=np.float64)
        if image is None or mask is None or image.shape != mask.shape or image.shape[1] != 2 * image.shape[0]:
            raise ValueError(f'Cannot read matching panorama and mask for frame {number}')
        if pose.shape != (3, 4) or not np.isfinite(pose).all() or not np.allclose(pose[:, :3].T @ pose[:, :3], np.eye(3), atol=1e-3) or np.linalg.det(pose[:, :3]) < .999:
            raise ValueError(f'Invalid camera-to-world pose for frame {number}')
        return image, np.where(mask >= 128, 255, 0).astype(np.uint8), pose
    image_a, mask_a, pose_a = read_frame(first_id)
    image_b, mask_b, pose_b = read_frame(second_id)
    if image_a.shape != image_b.shape:
        raise ValueError('Both frames must have the same resolution')
    detector = cv2.SIFT_create(nfeatures=3000)
    kp_a, desc_a = detector.detectAndCompute(image_a, mask_a)
    kp_b, desc_b = detector.detectAndCompute(image_b, mask_b)
    if desc_a is None or desc_b is None:
        raise ValueError('Insufficient texture to compute descriptors')
    matcher = cv2.BFMatcher()
    ab, ba = matcher.knnMatch(desc_a, desc_b, k=2), matcher.knnMatch(desc_b, desc_a, k=2)
    def good(pairs):
        return [pair[0] for pair in pairs if len(pair) == 2 and pair[0].distance < ratio * pair[1].distance]
    back = {match.queryIdx: match.trainIdx for match in good(ba)}
    matches = [match for match in good(ab) if back.get(match.trainIdx) == match.queryIdx]
    if len(matches) < 16:
        raise ValueError(f'Only {len(matches)} mutual matches; at least 16 are needed')
    points_a = np.asarray([kp_a[m.queryIdx].pt for m in matches])
    points_b = np.asarray([kp_b[m.trainIdx].pt for m in matches])
    height, width = image_a.shape
    world_a = image_rays(points_a, width, height) @ pose_a[:, :3].T
    world_b = image_rays(points_b, width, height) @ pose_b[:, :3].T
    predicted_rot = pose_a[:, :3].T @ pose_b[:, :3]
    return {'source_frames': [first_id, second_id], 'mutual_matches': len(matches),
            'baseline_arbitrary_units': float(np.linalg.norm(pose_b[:, 3] - pose_a[:, 3])),
            'predicted_relative_rotation_degrees': float(np.degrees(np.arccos(np.clip((np.trace(predicted_rot) - 1) / 2, -1, 1)))),
            'valid_fraction': [float(np.mean(mask_a >= 128)), float(np.mean(mask_b >= 128))],
            'diagnostic': pose_quality(world_a, world_b, points_a, width),
            'epipolar_diagnostic': epipolar_quality(world_a, world_b, pose_b[:, 3] - pose_a[:, 3]),
            'caveat': 'Pure rotation is fitted on the same frame pair; parallax, moving objects, incorrect matches, camera stitching and masks can also cause disagreement. Do not apply this as a pose correction.'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('dataset', type=Path)
    p.add_argument('first', type=int)
    p.add_argument('second', type=int)
    p.add_argument('--ratio', type=float, default=0.7, help='mutual SIFT nearest/second-nearest descriptor ratio')
    p.add_argument('--output', type=Path, help='new JSON file; default stdout')
    args = p.parse_args()
    if not 0 < args.ratio < 1 or args.first == args.second:
        p.error('ratio must be between 0 and 1 and frame indices must differ')
    text = json.dumps(analyze(args.dataset, args.first, args.second, args.ratio), indent=2, allow_nan=False) + '\n'
    if args.output:
        with args.output.open('x') as f: f.write(text)
    else: print(text, end='')


if __name__ == '__main__': main()
