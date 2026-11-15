"""Measure recovered Blender poses against known trajectory and scene geometry."""
import json
import sys
from pathlib import Path

import numpy as np


def evaluate(truth, result, imported):
    if len(truth) != len(result['frames']):
        raise ValueError('Ground-truth and sampled frame counts differ')
    selected = [row for row in result['frames'] if row['world_from_camera'] is not None]
    if len(selected) < 3:
        raise ValueError('At least three registered frames are required')
    gt_matrices = [np.array(truth[r['frame']]['world_from_blender_camera']) for r in selected]
    est_matrices = [np.array(imported[str(r['frame'])]) for r in selected]
    x = np.array([m[:3, 3] for m in est_matrices])
    y = np.array([m[:3, 3] for m in gt_matrices])
    xc, yc = x - x.mean(axis=0), y - y.mean(axis=0)
    variance = np.mean(np.sum(xc * xc, axis=1))
    if variance < 1e-15:
        raise ValueError('Cannot align a trajectory with no estimated translation')
    u, singular, vt = np.linalg.svd(yc.T @ xc / len(x))
    sign = np.eye(3)
    sign[-1, -1] = np.linalg.det(u @ vt)
    rotation = u @ sign @ vt
    scale = np.sum(singular * np.diag(sign)) / variance
    aligned = scale * (xc @ rotation.T) + y.mean(axis=0)
    translation_error = np.linalg.norm(aligned - y, axis=1)
    all_positions = np.array([np.array(row['world_from_blender_camera'])[:3, 3] for row in truth])
    path_length = np.sum(np.linalg.norm(np.diff(all_positions, axis=0), axis=1))
    if path_length < 1e-15:
        raise ValueError('Cannot normalize by a zero-length ground-truth path')
    angles = []
    pixel_error = []
    angular_error = []
    frame_p95 = []
    angular_frame_p95 = []
    for idx, (row, gm, em) in enumerate(zip(selected, gt_matrices, est_matrices)):
        delta = gm[:3, :3].T @ rotation @ em[:3, :3]
        angles.append(np.degrees(np.arccos(np.clip((np.trace(delta)-1)/2, -1, 1))))
        samples = np.array(truth[row['frame']].get('visible_world_points', []))
        if not len(samples):
            continue
        # Express the actual visible world points in the aligned recovered camera.
        camera_from_world_rotation = (rotation @ em[:3, :3]).T
        directions = (samples[:, 2:5] - aligned[idx]) @ camera_from_world_rotation.T
        directions /= np.linalg.norm(directions, axis=1)[:, None]
        # Blender camera axes: X right, Y up, -Z forward.
        predicted_u = (np.arctan2(directions[:, 0], -directions[:, 2]) / (2 * np.pi) + 0.5) % 1
        predicted_v = 0.5 - np.arcsin(np.clip(directions[:, 1], -1, 1)) / np.pi
        truth_u, truth_v = samples[:, 0] / 1024, samples[:, 1] / 512
        du = (predicted_u - truth_u + 0.5) % 1 - 0.5
        dv = predicted_v - truth_v
        per_point = np.sqrt(du**2 + dv**2)
        pixel_error.extend(per_point)
        frame_p95.append(np.percentile(per_point, 95))
        longitude = 2*np.pi*(truth_u-0.5)
        latitude = np.pi*(0.5-truth_v)
        true_rays = np.column_stack((np.sin(longitude)*np.cos(latitude), np.sin(latitude), -np.cos(longitude)*np.cos(latitude)))
        angular = np.degrees(np.arccos(np.clip(np.sum(directions*true_rays, axis=1), -1, 1)))
        angular_error.extend(angular)
        angular_frame_p95.append(np.percentile(angular, 95))
    report = {'registered': len(selected), 'sampled': len(truth), 'path_length': float(path_length), 'position_rmse': float(np.sqrt(np.mean(translation_error**2))), 'position_rmse_percent_path': float(100*np.sqrt(np.mean(translation_error**2))/path_length), 'position_max_percent_path': float(100*np.max(translation_error)/path_length), 'rotation_mean_degrees': float(np.mean(angles)), 'rotation_max_degrees': float(max(angles)), 'alignment_scale': float(scale), 'image_samples': len(pixel_error), 'image_sampled_frames': len(frame_p95)}
    if pixel_error:
        report.update({'image_rms_percent': float(100*np.sqrt(np.mean(np.square(pixel_error)))), 'image_p95_percent': float(100*np.percentile(pixel_error, 95)), 'image_worst_frame_p95_percent': float(100*max(frame_p95)), 'image_max_percent': float(100*np.max(pixel_error)), 'angular_rms_degrees': float(np.sqrt(np.mean(np.square(angular_error)))), 'angular_worst_frame_p95_degrees': float(max(angular_frame_p95)), 'angular_worst_frame_p95_percent_180': float(100*max(angular_frame_p95)/180)})
    return report


def main():
    if len(sys.argv) != 4:
        raise SystemExit('Usage: evaluate.py truth.json poses.json imported.json')
    truth, result, imported = [json.loads(Path(path).read_text()) for path in sys.argv[1:]]
    print(json.dumps(evaluate(truth, result, imported), indent=2))


if __name__ == '__main__':
    main()
