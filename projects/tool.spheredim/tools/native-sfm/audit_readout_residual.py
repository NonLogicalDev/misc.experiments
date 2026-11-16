"""Conditional readout-vs-SfM residual diagnostic; no physical timing claim."""
import argparse
import csv
import hashlib
import json
import time
from pathlib import Path
import cv2
import numpy as np
import compare_density_models as io
import compare_rigs as rig
from audit_seed_gauge import read_erp_cameras
from camera_basis import BODY_FROM_CV

basis_file = Path(__file__).with_name('camera_basis.py')

def validate_native_cameras(path):
    cams = read_erp_cameras(path)
    if any((c[:2] != (2048, 1024) or not np.allclose(c[2:], [2048, 1024], rtol=0, atol=1e-09) for c in cams.values())):
        raise ValueError('Expected native 2048 ERP cameras')
    return cams

def training_frames(manifest):
    rows = [x for x in manifest['frames'] if x['split'] == 'train']
    result = {x['source_name']: x for x in rows}
    if len(result) != len(rows):
        raise ValueError('Duplicate source names')
    return result

def signed_residual(points, rotation, center, xy, width, height):
    v = (points - center) @ rotation.T
    depth = np.linalg.norm(v, axis=1)
    lon = np.arctan2(v[:, 0], v[:, 2])
    lat = np.arctan2(v[:, 1], np.hypot(v[:, 0], v[:, 2]))
    src_lon = (xy[:, 0] / width - 0.5) * 2 * np.pi
    src_lat = (xy[:, 1] / height - 0.5) * np.pi
    dlon = (lon - src_lon + np.pi) % (2 * np.pi) - np.pi
    return (np.column_stack((dlon * np.cos(src_lat), lat - src_lat)) * 1024 / (2 * np.pi), depth)

def sha(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda: f.read(1048576), b''):
            h.update(b)
    return h.hexdigest()

def source_coordinates(ray, lens, lens_index, width, height):
    q = lens['orientation']
    rotation = rig.rotation([q['w'], q['x'], q['y'], q['z']])
    local = ray @ rotation.T
    denominator = local[:, 2] + lens['xi'] * np.linalg.norm(local, axis=1)
    good = np.isfinite(denominator) & (np.abs(denominator) > np.finfo(float).eps)
    x = np.divide(local[:, 0], denominator, out=np.full(len(ray), np.nan), where=good)
    y = np.divide(local[:, 1], denominator, out=np.full(len(ray), np.nan), where=good)
    r2 = x*x + y*y
    r4 = r2*r2
    k1, k2, k3, k4, k5, p1, p2, p3, p4, s1, s2, s3, s4 = lens['distortion_coefficients']
    radial = 1 + k1*r2 + k2*r4 + k3*r4*r2 + k4*r4*r4 + k5*r4*r4*r2
    xd = x*radial + (p1+r2*p3)*(r2+2*x*x) + 2*(p2+r2*p4)*x*y + s1*r2 + s3*r4
    yd = y*radial + (p2+r2*p4)*(r2+2*y*y) + 2*(p1+r2*p3)*x*y + s2*r2 + s4*r4
    half_canvas = lens['canvas_width'] / 2
    sx = (lens['cx'] + lens['fx']*xd - half_canvas*lens_index)*width/half_canvas
    sy = (lens['cy'] + lens['fy']*yd)*height/lens['canvas_height']
    return sx, sy, good

def rotation_design(ray):
    lon = np.arctan2(ray[:, 0], ray[:, 2])
    lat = np.arctan2(ray[:, 1], np.hypot(ray[:, 0], ray[:, 2]))
    east = np.column_stack((np.cos(lon), np.zeros(len(lon)), -np.sin(lon)))
    down = np.column_stack((-np.sin(lon) * np.sin(lat), np.cos(lat), -np.cos(lon) * np.sin(lat)))
    basis = np.eye(3)
    cross = np.stack([np.cross(axis, ray) for axis in basis], axis=2)
    return np.stack((np.einsum('ni,nij->nj', east, cross), np.einsum('ni,nij->nj', down, cross)), axis=1) * (1024 / (2 * np.pi))

def remove_rotation(res, pred, design):
    matrix = design.reshape(-1, 3)
    values = res.reshape(-1)
    prediction = pred.reshape(-1)
    weights = np.ones(len(values))
    for _ in range(6):
        root = np.sqrt(weights)
        coefficients = np.linalg.lstsq(matrix*root[:, None], values*root, rcond=None)[0]
        error = values - matrix@coefficients
        scale = 1.4826*np.median(np.abs(error-np.median(error))) + 1e-9
        weights = np.minimum(1, 1.345*scale/np.maximum(np.abs(error), 1e-15))
    root = np.sqrt(weights)
    weighted_matrix = matrix * root[:, None]
    residual_rotation = np.linalg.lstsq(weighted_matrix, values * root, rcond=None)[0]
    predicted_rotation = np.linalg.lstsq(weighted_matrix, prediction * root, rcond=None)[0]
    return ((values - matrix @ residual_rotation).reshape(-1, 2),
            (prediction - matrix @ predicted_rotation).reshape(-1, 2))

def robust_amplitude(x, y):
    x = x.ravel()
    y = y.ravel()
    den = np.dot(x, x)
    if den < 1e-15:
        return None
    a = float(np.dot(x, y) / den)
    for _ in range(12):
        r = y - a * x
        scale = 1.4826 * np.median(np.abs(r - np.median(r))) + 1e-09
        w = np.minimum(1, 1.345 * scale / np.maximum(np.abs(r), 1e-15))
        den = np.dot(w * x, x)
        if den < 1e-15:
            return None
        b = float(np.dot(w * x, y) / den)
        if abs(b - a) < 1e-09:
            break
        a = b
    return b

def integrate(t, v, query):
    if np.min(query) < t[0] or np.max(query) > t[-1]:
        raise ValueError('gyro time coverage missing')
    return np.column_stack([np.interp(query, t, v[:, j]) for j in range(3)])

def evaluate(parts):
    blocks = np.array([x['block'] for x in parts])
    result = []
    for hold in sorted(set(blocks)):
        tr = [x for x in parts if x['block'] != hold]
        te = [x for x in parts if x['block'] == hold]
        X = np.concatenate([x['pred'] for x in tr])
        Y = np.concatenate([x['res'] for x in tr])
        a = robust_amplitude(X, Y)
        xx = np.concatenate([x['pred'] for x in te])
        yy = np.concatenate([x['res'] for x in te])

        def mse(v):
            return float(np.mean((yy - v * xx) ** 2))
        nx = np.linalg.norm(xx)
        ny = np.linalg.norm(yy)
        result.append({'heldout_block': int(hold), 'train_frames': len(tr), 'test_frames': len(te), 'test_observations': len(xx), 'predictor_rms_px_per_component': float(np.sqrt(np.mean(xx**2))), 'residual_rms_px_per_component': float(np.sqrt(np.mean(yy**2))), 'learned_amplitude': a, 'signed_correlation': float(np.sum(xx * yy) / (nx * ny)) if nx and ny else None, 'test_mse_zero': mse(0), 'test_mse_fixed_plus1': mse(1), 'test_mse_fixed_minus1': mse(-1), 'test_mse_fitted': mse(a) if a is not None else None})
    return result

def main():
    p = argparse.ArgumentParser(description=__doc__)
    for n in ['model', 'prepared', 'calibration', 'metadata', 'gyro', 'frame_times', 'stream_probe', 'output']:
        p.add_argument(n, type=Path)
    p.add_argument('--timeout', type=int, default=180)
    a = p.parse_args()
    start = time.monotonic()
    assert not a.output.exists()
    man = json.loads((a.prepared / 'manifest.json').read_text())
    meta = json.loads(a.metadata.read_text())
    cal = json.loads(a.calibration.read_text())
    imu_metadata_path = a.gyro.parent / 'imu_metadata.json'
    imu_metadata = json.loads(imu_metadata_path.read_text())
    extraction_manifest_path = a.metadata.parents[2] / 'manifest.json'
    extraction_manifest = json.loads(extraction_manifest_path.read_text())
    if (imu_metadata['camera'] != 'Insta360 X5'
            or imu_metadata['angular_velocity_units'] != 'rad/s'
            or imu_metadata['gyro_adjust_ms'] != 1.6
            or imu_metadata['axis_transform'] != 'raw (x,y,z) to body (y,z,x), per insta360-rs X5 profile'
            or imu_metadata['source'] != extraction_manifest['inputs'][0]['source']):
        raise ValueError('Gyro coordinate, timing, or source provenance mismatch')
    assert meta['camera_name'] == 'Insta360 X5' and meta['rolling_shutter_time'] == 9.181875228881836 and (meta['gyro_timestamp_adjust_ms'] == 1.6) and (meta['file_rotation'] == 'Degrees0')
    assert cal['camera_model'] == 'X5' and all((x['model'] == 'OmniRadtanPro' for x in cal['lenses']))
    assert meta['crop_window']['unknown_fields'] == []
    validate_native_cameras(a.model / 'cameras.bin')
    streams = json.loads(a.stream_probe.read_text())['streams']
    if len(streams) != 2 or any((v['width'], v['height']) != (2880, 2880) for v in streams):
        raise ValueError('Expected the two recorded 2880-square streams')
    frames = training_frames(man)
    poses = rig.read_binary_poses(a.model / 'images.bin')
    obs = io.observations(a.model / 'images.bin')
    points = io.points(a.model / 'points3D.bin')
    with a.gyro.open() as f:
        rows = list(csv.DictReader(f))
        t = np.array([int(r['camera_timestamp_us']) for r in rows], dtype=float)
        w = np.array([[float(r[k]) for k in ('gyro_body_x_rad_s', 'gyro_body_y_rad_s', 'gyro_body_z_rad_s')] for r in rows])
        assert np.all(np.diff(t) > 0) and np.isfinite(w).all()
        v = np.vstack((np.zeros(3), np.cumsum((w[:-1] + w[1:]) * 0.5 * (np.diff(t) / 1000000.0)[:, None], axis=0)))
    with a.frame_times.open() as f:
        times = {int(r['frame']): float(r['gyro_query_camera_us']) for r in csv.DictReader(f)}
    ids = sorted(set((r['source_frame'] for r in frames.values())))
    block = {frame: min(4, 5 * i // len(ids)) for i, frame in enumerate(ids)}
    allout = {}
    mapping_counts = {}
    maskhash = {}
    for offset in (0.0, 0.5):
        variants = {str(k): [] for k in (0, -500000, 500000)}
        counts = {"candidate": 0, "invalid_denominator": 0, "out_of_bounds": 0, "valid": 0}
        for name, row in frames.items():
            if time.monotonic() - start > a.timeout:
                raise TimeoutError('Deadline exceeded')
            f = row['source_frame']
            assert f in times
            mp = a.prepared / 'masks' / row['name']
            maskhash[row['name']] = sha(mp)
            mask = cv2.imread(str(mp), 0)
            assert mask is not None and mask.shape == (1024, 2048)
            e = obs[name]
            xy = np.array(list(e), float).reshape(-1, 2)
            pid = np.array(list(e.values()), dtype=np.int64)
            if not len(xy):
                continue
            ix = np.rint(xy[:, 0]).astype(int)
            iy = np.rint(xy[:, 1]).astype(int)
            ok = (ix >= 0) & (ix < 2048) & (iy >= 0) & (iy < 1024)
            valid = np.zeros(len(xy), bool)
            valid[ok] = mask[iy[ok], ix[ok]] == 255
            valid &= np.array([int(x) in points for x in pid])
            xy = xy[valid]
            pid = pid[valid]
            if len(xy) < 8:
                continue
            xyz = np.array([points[int(i)] for i in pid])
            R, C = poses[name]
            res, _ = signed_residual(xyz, R, C, xy, 2048, 1024)
            lon = ((xy[:, 0] + offset) / 2048 - 0.5) * 2 * np.pi
            lat = ((xy[:, 1] + offset) / 1024 - 0.5) * np.pi
            ray = np.column_stack((np.sin(lon) * np.cos(lat), np.sin(lat), np.cos(lon) * np.cos(lat)))
            body = ray @ BODY_FROM_CV.T
            lens_index = int(row['lens'][-1])
            lens = cal['lenses'][lens_index]
            width, height = streams[lens_index]['width'], streams[lens_index]['height']
            sx, sy, denominator_ok = source_coordinates(body, lens, lens_index, width, height)
            valid = denominator_ok & np.isfinite(sx) & np.isfinite(sy) & (sx >= 0) & (sx <= width-1) & (sy >= 0) & (sy <= height-1)
            counts['candidate'] += len(sy)
            counts['invalid_denominator'] += int((~denominator_ok).sum())
            counts['out_of_bounds'] += int((denominator_ok & ~valid).sum())
            counts['valid'] += int(valid.sum())
            ray = ray[valid]
            res = res[valid]
            sy = sy[valid]
            if len(sy) < 8:
                continue
            dt = ((sy + 0.5) / height - 0.5) * meta['rolling_shutter_time'] * 1000
            design = rotation_design(ray)
            center = times[f]
            for shift in (0, -500000, 500000):
                query = np.concatenate(([center + shift], center + shift + dt))
                integ = integrate(t, v, query)
                delta = (integ[1:] - integ[0]) @ BODY_FROM_CV
                pred = np.einsum('nij,nj->ni', design, delta)
                yr, xr = remove_rotation(res, pred, design)
                variants[str(shift)].append({'block': block[f], 'frame': f, 'pred': xr, 'res': yr})
        allout[str(offset)] = {k: evaluate(v) for k, v in variants.items()}
        mapping_counts[str(offset)] = counts
    inputs = [a.model / 'cameras.bin', a.model / 'images.bin', a.model / 'points3D.bin', a.prepared / 'manifest.json', a.calibration, a.metadata, a.gyro, a.frame_times, a.stream_probe, imu_metadata_path, extraction_manifest_path, basis_file, Path(__file__)]
    out = {'method': 'Conditional infinitesimal gyro integration in physical body coordinates; SfM prediction minus observed ERP bearing; both residual and predictor projected off three per-frame common rotation modes with shared Huber weights derived from residuals. Heldout MSE is unweighted and can remain sensitive to outliers. Five chronological heldout blocks; robust fit on other blocks. Fixed +1/-1 errors are distinct; changing direction while refitting a signed amplitude is algebraically equivalent.', 'caveats': ['SfM fitted these observations; diagnostic holdout blocks are not independent geometry. Tracks and adjacent frames are correlated.', 'Continuous feature-to-sensor row and pixel-center conventions are unverified hypotheses; actual saved source-coordinate maps absent.', 'Gyro timing and exposure mapping are exploratory; secondary exposure record absent and common clock is assumed. Tag25 duration and top-to-bottom direction are model assumptions, not physical measurement.', 'Rotation-only first-order approximation; ignores translation during readout and nonlinear accumulation.', 'Confidence intervals are not claimed; report per-block stability.'], 'readout_ms': meta['rolling_shutter_time'], 'time_shifts_us': [0, -500000, 500000], 'pixel_offsets': allout, 'mapping_counts': mapping_counts, 'source_streams': streams, 'input_sha256': {str(x): sha(x) for x in inputs}, 'mask_sha256': maskhash, 'elapsed_seconds': time.monotonic() - start}
    text = json.dumps(out, indent=2, allow_nan=False) + '\n'
    assert len(text.encode()) < 1000000
    a.output.write_text(text)
    print(json.dumps({'elapsed_seconds': out['elapsed_seconds'], 'pixel_offsets': allout}, indent=2))
if __name__ == '__main__':
    main()
