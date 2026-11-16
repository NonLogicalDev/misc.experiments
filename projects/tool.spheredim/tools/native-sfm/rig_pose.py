"""Fit a physical rig pose to world landmarks and lens-frame unit bearings."""
import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation


def fit_rig_pose(points, bearings, members, extrinsics, initial, *, threshold_radians=0.01):
    """Return world-to-rig pose and inlier mask; never move landmarks or lenses.

    extrinsics[m] is (camera-from-rig rotation, camera-from-rig translation).
    initial is (rig-from-world rotation, rig-from-world translation).
    Correspondence deduplication and acceptance gates belong to the caller.
    """
    points = np.asarray(points, dtype=float)
    bearings = np.asarray(bearings, dtype=float)
    members = np.asarray(members, dtype=int)
    if points.ndim != 2 or points.shape[1] != 3 or bearings.shape != points.shape or members.shape != (len(points),):
        raise ValueError('Invalid correspondence shapes')
    if len(points) < 6 or not np.isfinite(points).all() or not np.isfinite(bearings).all():
        raise ValueError('Too few or invalid correspondences')
    norms = np.linalg.norm(bearings, axis=1)
    if np.any(np.abs(norms - 1) > 1e-6) or threshold_radians <= 0:
        raise ValueError('Invalid bearing or threshold')
    if np.any(members < 0) or np.any(members >= len(extrinsics)):
        raise ValueError('Unknown rig member')
    rotations = np.stack([np.asarray(r, dtype=float) for r, _ in extrinsics])
    translations = np.stack([np.asarray(t, dtype=float) for _, t in extrinsics])
    if rotations.shape != (len(extrinsics), 3, 3) or translations.shape != (len(extrinsics), 3):
        raise ValueError('Invalid rig extrinsics')
    if not np.isfinite(rotations).all() or not np.isfinite(translations).all():
        raise ValueError('Invalid rig extrinsics')
    def projected(x):
        rig = points @ Rotation.from_rotvec(x[:3]).as_matrix().T + x[3:]
        camera = np.einsum('nij,nj->ni', rotations[members], rig) + translations[members]
        lengths = np.linalg.norm(camera, axis=1)
        if np.any(lengths < 1e-12):
            raise ValueError('Point at camera center')
        return camera / lengths[:, None]
    def residual(x):
        return (projected(x) - bearings).ravel()
    x0 = np.r_[Rotation.from_matrix(initial[0]).as_rotvec(), initial[1]]
    result = least_squares(residual, x0, loss='soft_l1', f_scale=threshold_radians, max_nfev=300)
    predicted = projected(result.x)
    angles = np.arctan2(np.linalg.norm(np.cross(predicted, bearings), axis=1), np.einsum('ij,ij->i', predicted, bearings))
    inliers = angles <= threshold_radians
    return Rotation.from_rotvec(result.x[:3]).as_matrix(), result.x[3:], inliers, result.success


def validate_registration(inliers, point_ids, members, pixels, source_timestamps, *, min_landmarks, min_per_lens, min_regions_per_lens, min_source_timestamps, image_size=(1024, 512)):
    """Apply caller-selected evidence gates; duplicate orientations do not vote twice.

    Four-by-four image regions measure spread within each physical lens, not
    physical surface coverage. Thresholds must be reported as experimental.
    """
    inliers = np.asarray(inliers, dtype=bool)
    point_ids = np.asarray(point_ids)
    members = np.asarray(members)
    pixels = np.asarray(pixels, dtype=float)
    source_timestamps = np.asarray(source_timestamps)
    n = len(inliers)
    if any(len(a) != n for a in (point_ids, members, pixels, source_timestamps)) or pixels.shape != (n, 2):
        raise ValueError('Invalid registration evidence')
    width, height = image_size
    if width <= 0 or height <= 0 or not np.isfinite(pixels).all() or np.any(pixels[:,0] < 0) or np.any(pixels[:,0] >= width) or np.any(pixels[:,1] < 0) or np.any(pixels[:,1] >= height):
        raise ValueError('Invalid source pixel')
    if np.any((members != 0) & (members != 1)):
        raise ValueError('Expected two physical lenses')
    total = len(set(point_ids[inliers].tolist()))
    per_lens = []
    regions = []
    for lens in (0, 1):
        mask = inliers & (members == lens)
        per_lens.append(len(set(point_ids[mask].tolist())))
        region = {(int(4*x/width), int(4*y/height)) for x,y in pixels[mask]}
        regions.append(len(region))
    timestamps = len(set(source_timestamps[inliers].tolist()))
    accepted = (total >= min_landmarks and min(per_lens) >= min_per_lens and
                min(regions) >= min_regions_per_lens and timestamps >= min_source_timestamps)
    return {'accepted': bool(accepted), 'distinct_landmarks': total, 'distinct_landmarks_per_lens': per_lens,
            'regions_per_lens': regions, 'source_timestamps': timestamps}


def validate_fixed_rig(paired_poses, extrinsics, *, rotation_tolerance_radians, translation_tolerance):
    """Verify nonzero fixed extrinsics against world-to-camera paired poses."""
    if len(extrinsics) != 2 or len(paired_poses) == 0:
        raise ValueError('Expected a two-lens rig and paired poses')
    r0, t0 = extrinsics[0]
    r1, t1 = extrinsics[1]
    r0, t0, r1, t1 = map(np.asarray, (r0,t0,r1,t1))
    expected_r = r1 @ r0.T
    expected_t = t1 - expected_r @ t0
    baseline = float(np.linalg.norm(expected_t))
    if not np.isfinite(baseline) or baseline <= 0:
        raise ValueError('Rig baseline must be nonzero')
    max_rotation = max_translation = 0.
    for (a_r, a_t), (b_r, b_t) in paired_poses:
        relative_r = np.asarray(b_r) @ np.asarray(a_r).T
        relative_t = np.asarray(b_t) - relative_r @ np.asarray(a_t)
        angle = np.linalg.norm(Rotation.from_matrix(relative_r @ expected_r.T).as_rotvec())
        delta = np.linalg.norm(relative_t - expected_t)
        max_rotation, max_translation = max(max_rotation, angle), max(max_translation, delta)
    if max_rotation > rotation_tolerance_radians or max_translation > translation_tolerance:
        raise ValueError('Original paired poses disagree with fixed rig')
    return {'baseline': baseline, 'max_rotation_error_radians': max_rotation,
            'max_translation_error': max_translation}
