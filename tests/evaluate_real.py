"""Compare a sampled 360DVO trajectory with the authors' pseudo-ground-truth positions."""
import json
import sys
from pathlib import Path
import numpy as np


def main():
    if len(sys.argv) != 4:
        raise SystemExit('Usage: evaluate_real.py trajectory.txt poses.json source-frame-step')
    truth = np.loadtxt(sys.argv[1])[:, :3]
    result = json.loads(Path(sys.argv[2]).read_text())
    step = int(sys.argv[3])
    if step < 1 or (len(result['frames'])-1)*step >= len(truth):
        raise ValueError('Reference trajectory does not cover the sampled frames')
    poses = [row for row in result['frames'] if row['world_from_camera'] is not None]
    if len(poses) < 3:
        raise ValueError('At least three registered frames are required')
    x = np.array([np.array(row['world_from_camera'])[:3, 3] for row in poses])
    y = np.array([truth[row['frame'] * step] for row in poses])
    xc, yc = x-x.mean(axis=0), y-y.mean(axis=0)
    variance = np.mean(np.sum(xc*xc, axis=1))
    if variance < 1e-15:
        raise ValueError('Estimated trajectory has no translation')
    u, singular, vt = np.linalg.svd(yc.T @ xc / len(x))
    sign = np.eye(3)
    sign[-1, -1] = np.linalg.det(u @ vt)
    rotation = u @ sign @ vt
    scale = np.sum(singular * np.diag(sign)) / variance
    error = np.linalg.norm(scale * xc @ rotation.T + y.mean(axis=0) - y, axis=1)
    gt_used = truth[:(len(result['frames'])-1)*step+1]
    length = np.sum(np.linalg.norm(np.diff(gt_used, axis=0), axis=1))
    if length < 1e-15:
        raise ValueError('Reference trajectory has no translation')
    print(json.dumps({'registered':len(poses), 'sampled':len(result['frames']), 'path_length_reference_units':float(length), 'position_rmse_reference_units':float(np.sqrt(np.mean(error**2))), 'position_rmse_percent_path':float(100*np.sqrt(np.mean(error**2))/length), 'position_max_percent_path':float(100*max(error)/length), 'alignment_scale':float(scale)}, indent=2))


if __name__ == '__main__':
    main()
