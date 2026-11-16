#!/usr/bin/env python3
"""Fit a three-parameter plane to fixed native ERP training patches."""
import argparse
import itertools
import json
import time
from pathlib import Path

import cv2
import numpy as np
from scipy.optimize import minimize
import compare_planar_transfer as transfer
import compare_rigs as rig

TRAIN = (1485, 1490, 1495)
CHECK = (1505, 1440, 1560)
W, H = 2048, 1024


def plane(params, normal, d, scale):
    axis = np.eye(3)[np.argmin(np.abs(normal))]
    u = np.cross(normal, axis)
    u /= np.linalg.norm(u)
    v = np.cross(normal, u)
    n = normal + np.tan(params[0]) * u + np.tan(params[1]) * v
    n /= np.linalg.norm(n)
    return n, d + params[2] * scale


def samples(params, normal, d, scale, xy, source_pose, target_pose, image, mask):
    n, offset = plane(params, normal, d, scale)
    x, y, positive = transfer.inverse_plane_map(xy[:, 0], xy[:, 1], source_pose, target_pose, n, offset)
    values, valid = transfer.bilinear_rgb(image, mask, x, y)
    return values, bool(np.all(valid & positive))


def normalized_residual(source, target):
    a = source.reshape(-1, 49, 3).mean(axis=2)
    b = target.reshape(-1, 49, 3).mean(axis=2)
    a = a - a.mean(axis=1, keepdims=True)
    b = b - b.mean(axis=1, keepdims=True)
    sa = np.linalg.norm(a, axis=1, keepdims=True)
    sb = np.linalg.norm(b, axis=1, keepdims=True)
    if np.any(sa < 1e-6) or np.any(sb < 1e-6):
        return None
    return ((a / sa) - (b / sb)).ravel()


def fit_plane(source, xy, source_pose, targets, normal, d, scale, deadline):
    bounds = [(-np.deg2rad(3), np.deg2rad(3))] * 2 + [(-.05, .05)]
    invalid = 0
    def residual(params):
        nonlocal invalid
        if time.monotonic() > deadline:
            raise TimeoutError('CPU deadline')
        rows = []
        for image, mask, pose in targets:
            values, valid = samples(params, normal, d, scale, xy, source_pose, pose, image, mask)
            r = normalized_residual(source, values) if valid else None
            if r is None:
                invalid += 1
                return None
            rows.append(r / np.sqrt(len(r)))
        return np.concatenate(rows)
    def objective(params):
        r = residual(params)
        if r is None:
            return 1e3
        # Smooth robust loss; each view has the same number of fixed samples.
        return float(np.sum(2 * .02**2 * (np.sqrt(1 + (r / .02)**2) - 1)))
    starts = ([0, 0, 0], [0, 0, -.025], [0, 0, .025])
    attempts = []
    for start in starts:
        result = minimize(objective, start, method='Powell', bounds=bounds,
                          options={'maxiter': 25, 'maxfev': 450, 'xtol': 1e-5, 'ftol': 1e-7})
        score = objective(result.x)
        attempts.append({'x': result.x.tolist(), 'cost': score, 'success': bool(result.success), 'evaluations': int(result.nfev)})
    valid = [x for x in attempts if x['cost'] < 1e3]
    if not valid:
        raise ValueError('No feasible optimization result')
    best = min(valid, key=lambda x: x['cost'])
    x = np.array(best['x'])
    jac = []
    for i in range(3):
        delta = np.zeros(3); delta[i] = 1e-5
        a, b = residual(x + delta), residual(x - delta)
        if a is None or b is None:
            return best, attempts, invalid, None
        jac.append((a - b) / (2e-5))
    singular = np.linalg.svd(np.column_stack(jac), compute_uv=False)
    return best, attempts, invalid, singular.tolist()



def classify(best, singular, bound_hits, distinct, required_support):
    """Classify a numerical plane hypothesis, never physical depth truth."""
    condition = None if singular is None or singular[-1] < 1e-12 else singular[0] / singular[-1]
    good = best['success'] and condition is not None and condition < 1000
    good = good and not any(bound_hits) and not distinct and required_support
    return ('hypothesis fitted' if good else 'unresolved'), condition

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('data', type=Path)
    parser.add_argument('model', type=Path)
    parser.add_argument('prior', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    start = time.monotonic()
    prior = json.loads(args.prior.read_text())
    if transfer.digest(args.model / 'images.bin') != prior['model_sha256']['images.bin']:
        raise ValueError('Original model differs from prior')
    from pose_sensitivity import validate_original_cameras
    validate_original_cameras(args.model / 'cameras.bin')
    poses = rig.read_poses(args.data / 'sparse/0')
    original = rig.read_binary_poses(args.model / 'images.bin')
    def load(frame, split):
        name = f'{split}_{frame:06d}_cam0.png'
        pose = poses[name]
        source_name = f'cam0/frame_{frame:06d}.png'
        if not all(np.allclose(a, b, rtol=0, atol=1e-8) for a, b in zip(pose, original[source_name])):
            raise ValueError('Pose mismatch: ' + name)
        ip, mp = args.data/'images'/name, args.data/'masks'/name
        image, mask = cv2.imread(str(ip)), cv2.imread(str(mp), 0)
        if image is None or image.shape != (H, W, 3) or mask is None or mask.shape != (H, W):
            raise ValueError('Invalid input: ' + name)
        if str(frame) in prior['input_views']:
            row = prior['input_views'][str(frame)]
            if transfer.digest(ip) != row['image_sha256'] or transfer.digest(mp) != row['mask_sha256']:
                raise ValueError('Input differs from prior: ' + name)
        return image, mask, pose, {'name': name, 'image_sha256': transfer.digest(ip), 'mask_sha256': transfer.digest(mp)}
    ref = load(1500, 'train')
    train = [load(i, 'train') for i in TRAIN]
    normal = np.array(prior['plan']['plane_normal'])
    d, scale = prior['plan']['plane_d'], prior['plan']['median_range_model_units']
    landmarks = [r['xy'] for r in prior['plane_landmarks'] if r['inlier']]
    hull = transfer.hull_support((H, W), landmarks)
    safe = cv2.erode(((hull == 255) & (ref[1] == 255)).astype(np.uint8), np.ones((7, 7), np.uint8))
    candidates = []
    for y, x in itertools.product(range(443, 690, 8), range(453, 700, 8)):
        if safe[y, x]:
            candidates.append((x, y))
    offsets = np.array(list(itertools.product(range(-3, 4), repeat=2)))
    centers, patches = [], []
    for x, y in candidates:
        xy = np.column_stack((x + offsets[:, 0], y + offsets[:, 1]))
        source = ref[0][xy[:, 1], xy[:, 0]]
        if source.mean(axis=1).std() < 5:
            continue
        if all(samples([0, 0, 0], normal, d, scale, xy, ref[2], t[2], t[0], t[1])[1] for t in train):
            centers.append((x, y)); patches.append(xy)
    if len(patches) < 12:
        raise ValueError('Insufficient initially valid textured patches')
    xy = np.concatenate(patches)
    source = ref[0][xy[:, 1], xy[:, 0]].astype(float)
    best, attempts, invalid, singular = fit_plane(source, xy, ref[2], [t[:3] for t in train], normal, d, scale, start + 55)
    bound_hits = [bool(abs(x) >= .99*b) for x, b in zip(best['x'], [np.deg2rad(3), np.deg2rad(3), .05])]
    distinct = [a for a in attempts if a['cost'] < 1000 and np.linalg.norm(np.array(a['x']) - best['x']) > .005 and a['cost'] <= best['cost'] * 1.01]
    training = []
    for t in train:
        baseline, _ = samples([0, 0, 0], normal, d, scale, xy, ref[2], t[2], t[0], t[1])
        fitted, _ = samples(best['x'], normal, d, scale, xy, ref[2], t[2], t[0], t[1])
        training.append({'name': t[3]['name'], 'baseline_raw_mse': float(np.mean((source-baseline)**2)/255**2), 'fitted_raw_mse': float(np.mean((source-fitted)**2)/255**2), 'baseline_normalized_rms': float(np.sqrt(np.mean(normalized_residual(source, baseline)**2))), 'fitted_normalized_rms': float(np.sqrt(np.mean(normalized_residual(source, fitted)**2)))})
    # Only now open reserved and evaluation observations.
    checks = [load(i, 'train' if i == 1505 else 'eval') for i in CHECK]
    comparisons = []
    for t in checks:
        baseline, good0 = samples([0, 0, 0], normal, d, scale, xy, ref[2], t[2], t[0], t[1])
        fitted, good1 = samples(best['x'], normal, d, scale, xy, ref[2], t[2], t[0], t[1])
        # Freeze the initially valid samples, without dropping failed fitted samples.
        if not good0 or not good1:
            comparisons.append({'name': t[3]['name'], 'status': 'unresolved: fixed patch support invalid'})
            continue
        comparisons.append({'name': t[3]['name'], 'baseline_raw_mse': float(np.mean((source-baseline)**2)/255**2), 'fitted_raw_mse': float(np.mean((source-fitted)**2)/255**2)})
    status, condition = classify(best, singular, bound_hits, distinct, all('status' not in c for c in comparisons))
    fitted_normal, fitted_d = plane(best['x'], normal, d, scale)
    cells = set(((x-450)//63, (y-440)//63) for x,y in centers)
    report = {'status': status, 'parameterization': 'normal proportional to initial normal plus tangent vectors scaled by tan(angle); d_new = d_initial + parameter_3 times reference median range; offset is origin based', 'fitted_normal': fitted_normal.tolist(), 'fitted_d': float(fitted_d), 'method': 'Three plane parameters in original SfM gauge; fixed source patches and training observations, candidate wholly infeasible on any invalid bilinear tap or nonpositive depth; raw native ERP pixels; target projection uses +0.5 and -0.5 renderer centers. SfM used evaluation captures. Plane hypothesis is not depth truth.', 'initial_candidates': len(candidates), 'fixed_patches': len(patches), 'roi_cells_4x4': len(cells), 'attempts': attempts, 'best': best, 'bound_hits': bound_hits, 'invalid_candidates': invalid, 'jacobian_singular_values': singular, 'jacobian_condition': condition, 'comparable_distinct_minima': len(distinct), 'training': training, 'checks': comparisons, 'inputs': [ref[3]] + [t[3] for t in train + checks], 'prior_sha256': transfer.digest(args.prior), 'model_images_sha256': transfer.digest(args.model/'images.bin'), 'script_sha256': transfer.digest(Path(__file__)), 'elapsed_seconds': time.monotonic()-start}
    encoded = (json.dumps(report, indent=2, allow_nan=False)+'\n').encode()
    if len(encoded) > 1_000_000: raise ValueError('Output exceeds limit')
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output/'report.json').write_bytes(encoded)
    print(json.dumps(report, indent=2))

if __name__ == '__main__': main()
