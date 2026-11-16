#!/usr/bin/env python3
"""Register paired spherical features against a fixed, indexed rig reconstruction."""
import argparse
import hashlib
import json
import struct
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

import compare_rigs
from recover_landmark_descriptors import read_features, recover
from rig_pose import fit_rig_pose, validate_fixed_rig, validate_registration


def digest(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def match_distinct_landmarks(query, descriptors, point_ids, ratio=0.8):
    """Return (query row, source row, distance) using two distinct landmarks.

    Multiple descriptors of one landmark compete as one alternative. Work in
    bounded query batches; ties between different landmarks fail the ratio.
    """
    query = np.asarray(query, dtype=np.float32)
    descriptors = np.asarray(descriptors, dtype=np.float32)
    point_ids = np.asarray(point_ids)
    if query.ndim != 2 or descriptors.ndim != 2 or query.shape[1] != descriptors.shape[1] or len(point_ids) != len(descriptors) or not 0 < ratio < 1:
        raise ValueError('Invalid descriptors or ratio')
    unique, inverse = np.unique(point_ids, return_inverse=True)
    if len(unique) < 2:
        return []
    desc_norm = np.einsum('ij,ij->i', descriptors, descriptors)
    result = []
    for start in range(0, len(query), 64):
        part = query[start:start+64]
        distances = np.maximum(0, np.einsum('ij,ij->i', part, part)[:,None] + desc_norm[None,:] - 2 * part @ descriptors.T)
        for offset, d in enumerate(distances):
            best = np.full(len(unique), np.inf)
            np.minimum.at(best, inverse, d)
            two = np.argpartition(best, 1)[:2]
            two = two[np.argsort(best[two])]
            if best[two[0]] < ratio * ratio * best[two[1]]:
                candidates = np.flatnonzero(inverse == two[0])
                row = int(candidates[np.argmin(d[candidates])])
                result.append((start + offset, row, float(np.sqrt(best[two[0]]))))
    return result


def uncertainty(points, bearings, members, extrinsics, R, t, inliers):
    """Linearized local conditioning, not a confidence interval or accuracy proof."""
    points = np.asarray(points)[inliers]
    bearings = np.asarray(bearings)[inliers]
    members = np.asarray(members)[inliers]
    if len(points) < 6:
        return {'valid': False, 'reason': 'too few inliers'}
    x = np.r_[Rotation.from_matrix(R).as_rotvec(), t]
    def residual(v):
        p = points @ Rotation.from_rotvec(v[:3]).as_matrix().T + v[3:]
        cam = np.array([extrinsics[m][0] @ q + extrinsics[m][1] for q,m in zip(p,members)])
        length = np.linalg.norm(cam, axis=1)
        if np.any(length < 1e-12):
            raise ValueError('Point at camera center')
        return (cam / length[:,None] - bearings).ravel()
    v = residual(x)
    step = 1e-6
    jac = np.column_stack([(residual(x + np.eye(6)[i]*step) - residual(x - np.eye(6)[i]*step))/(2*step) for i in range(6)])
    _, singular, vt = np.linalg.svd(jac, full_matrices=False)
    rank = int(np.sum(singular > singular[0] * 1e-10)) if singular[0] else 0
    if rank != 6:
        return {'valid': False, 'reason': 'rank-deficient pose geometry', 'rank': rank}
    condition = float(singular[0] / singular[-1])
    sigma = float(np.linalg.norm(v) / np.sqrt(max(1, len(v) - 6)))
    covariance = (vt.T * (sigma / singular)**2) @ vt
    std = np.sqrt(np.maximum(np.diag(covariance), 0))
    return {'valid': bool(np.isfinite(condition) and np.isfinite(std).all()), 'rank': rank, 'condition': condition,
            'rotation_parameter_std_degrees': np.degrees(std[:3]).tolist(), 'translation_parameter_std': std[3:].tolist()}


def features(path):
    with path.open('rb') as f:
        header = struct.unpack('<4s6I', f.read(28))
    keypoints, raw, dim = read_features(path, header[4])
    return keypoints, np.frombuffer(raw, np.uint8).reshape(-1, dim)


def rig_calibration(path):
    rows = [line.split() for line in path.read_text().splitlines() if line and not line.startswith('#')]
    if len(rows) != 2 or rows[0][1:3] != ['cam0','cam0'] or rows[1][1:3] != ['cam1','cam0']:
        raise ValueError('Expected cam0 reference and cam1 physical rig')
    ext = [(compare_rigs.rotation(list(map(float,row[3:7]))), np.array(list(map(float,row[7:10])))) for row in rows]
    return ext


def register(model, workspace, selection, new_features, feature_manifest, input_manifest, anchor_manifest, seed, output,
             *, ratio=0.8, threshold=0.01, min_landmarks=30, min_per_lens=8, min_regions=3,
             min_timestamps=2, max_condition=1e6):
    """Create a separate report; failed frames never receive a candidate pose."""
    model, workspace, selection, new_features, feature_manifest, input_manifest, anchor_manifest, seed, output = map(Path,
        (model, workspace, selection, new_features, feature_manifest, input_manifest, anchor_manifest, seed, output))
    if output.exists():
        raise FileExistsError(output)
    selected = json.loads(selection.read_text())['frames']
    inputs = json.loads(input_manifest.read_text())['frames']
    provenance = json.loads(feature_manifest.read_text())
    if provenance.get('input_manifest_sha256') != digest(input_manifest):
        raise ValueError('Features are not tied to the supplied input manifest')
    by_frame = {row['source_frame']: row for row in inputs}
    anchors = {row['source_frame']: row['timestamp_microseconds'] for row in json.loads(anchor_manifest.read_text())['frames']}
    if not selected or len(by_frame) != len(inputs) or len({r['frame'] for r in selected}) != len(selected):
        raise ValueError('Invalid selection or input frames')
    original_files = [model/'images.bin', model/'points3D.bin', model/'rigs.txt', workspace/'matches.bin', seed]
    hashes_before = {str(p): digest(p) for p in original_files}
    poses = compare_rigs.read_poses(model)
    ext = rig_calibration(model/'rigs.txt')
    pairs = []
    for item in selected:
        inp = by_frame.get(item['frame'])
        if inp is None or item['timestamp_microseconds'] != inp['timestamp_microseconds']:
            raise ValueError('Selection and source timestamps disagree')
        pair=[]
        for lens in (0,1):
            r, center = poses[f"cam{lens}/frame_{item['anchor']:06d}.png"]
            pair.append((r, -r @ center))
        if item['anchor'] not in anchors:
            raise ValueError('Anchor timestamp missing')
        pairs.append(pair)
    rig = validate_fixed_rig(pairs, ext, rotation_tolerance_radians=1e-7, translation_tolerance=1e-7)
    results=[]; source_features={}
    available = sorted({int(Path(n).stem.split('_')[-1]) for n in poses if n.startswith('cam0/frame_')})
    for item in selected:
        frame, anchor = item['frame'], item['anchor']
        nearest = sorted(available, key=lambda f:(abs(f-anchor), f))
        # Restrict by temporal proximity before sorting into recording order.
        sources = sorted([f for f in nearest if f != frame and f'cam1/frame_{f:06d}.png' in poses][:5])
        names = [f'cam{lens}/frame_{f:06d}.png' for f in sources for lens in (0,1)]
        observations = recover(model, workspace, names)
        for name in names:
            p=workspace/'features'/Path(name).with_suffix('.bin'); source_features[str(p)] = digest(p)
        candidates=[]; keypoints=[]
        for lens in (0,1):
            rows=[o for o in observations if o.image.startswith(f'cam{lens}/')]
            file = new_features/f'cam{lens}/frame_{frame:06d}.bin'
            key = f'features/cam{lens}/frame_{frame:06d}.bin'
            if digest(file) != provenance['features'].get(key):
                raise ValueError(f'New feature hash mismatch: {file}')
            kp, query = features(file); keypoints.append(kp)
            if not rows or len(query)==0: continue
            descriptors = np.array([list(o.descriptor) for o in rows], dtype=np.uint8)
            for q, src, distance in match_distinct_landmarks(query, descriptors, [o.point_id for o in rows], ratio):
                candidates.append((distance, lens, q, rows[src]))
        points=[]; rays=[]; members=[]; ids=[]; pixels=[]; timestamps=[]; used=set()
        for distance, lens, q, obs in sorted(candidates, key=lambda v:v[0]):
            if obs.point_id in used: continue
            used.add(obs.point_id)
            x,y=keypoints[lens][q][:2]
            points.append(obs.xyz); rays.append(compare_rigs.ray(x,y,1024,512)); members.append(lens)
            ids.append(obs.point_id); pixels.append((x,y)); timestamps.append(int(Path(obs.image).stem.split('_')[-1]))
        report={'source_frame':frame, 'timestamp_microseconds':item['timestamp_microseconds'], 'anchor_source_frame':anchor,
                'anchor_timestamp_microseconds':anchors[anchor], 'landmark_source_frames':sources, 'landmark_source_timestamps_microseconds':[anchors[f] for f in sources], 'descriptor_landmarks':len(ids), 'accepted':False}
        initial_r, initial_center = poses[f'cam0/frame_{anchor:06d}.png']
        initial_t = -initial_r @ initial_center
        report['anchor_rig_from_world']={'rotation':initial_r.tolist(),'translation':initial_t.tolist()}
        if len(ids) >= 6:
            r,t,inliers,success = fit_rig_pose(points,rays,members,ext,(initial_r,initial_t),threshold_radians=threshold)
            def residual_summary(rr,tt):
                predicted=np.asarray(points)@rr.T+tt
                predicted=np.array([ext[m][0]@v+ext[m][1] for v,m in zip(predicted,members)])
                predicted/=np.linalg.norm(predicted,axis=1)[:,None]
                observed=np.asarray(rays)
                errors=np.arctan2(np.linalg.norm(np.cross(predicted,observed),axis=1),np.einsum('ij,ij->i',predicted,observed))[inliers]*1024/(2*np.pi)
                return {'median_erp_pixels':float(np.median(errors)), 'p90_erp_pixels':float(np.quantile(errors,.9))} if len(errors) else None
            report['inlier_residuals_at_anchor']=residual_summary(initial_r,initial_t)
            report['inlier_residuals_at_fit']=residual_summary(r,t)
            gate = validate_registration(inliers,ids,members,pixels,timestamps,min_landmarks=min_landmarks,
                min_per_lens=min_per_lens,min_regions_per_lens=min_regions,min_source_timestamps=min_timestamps)
            quality=uncertainty(points,rays,members,ext,r,t,inliers)
            report.update(gate);report['uncertainty']=quality
            report['solver_success']=bool(success)
            report['accepted']=bool(success and gate['accepted'] and quality['valid'] and quality['condition'] <= max_condition)
            report['anchor_rotation_difference_degrees']=float(np.degrees(np.linalg.norm(Rotation.from_matrix(r@initial_r.T).as_rotvec())))
            report['anchor_center_difference_scene_units']=float(np.linalg.norm(-r.T@t-initial_center))
            if report['accepted']:
                report['rig_from_world']={'rotation':r.tolist(),'translation':t.tolist()}
            else:
                report['failure']='solver, evidence or conditioning gate failed; retain original anchor'
        else:
            report['failure']='too few correspondences; retain original anchor'
        results.append(report)
    if hashes_before != {str(p):digest(p) for p in original_files}:
        raise ValueError('Original model, match graph or seed changed during registration')
    report={'method':'Experimental local spherical rig fit; uncertainty is linearized conditioning, not independent accuracy. Image-region gates do not establish surface coverage.',
            'parameters':{'ratio':ratio,'threshold_radians':threshold,'min_landmarks':min_landmarks,'min_per_lens':min_per_lens,
                          'min_regions_per_lens':min_regions,'min_source_timestamps':min_timestamps,'max_condition':max_condition},
            'input_sha256':hashes_before | {str(p):digest(p) for p in (selection,feature_manifest,input_manifest,anchor_manifest)},
            'source_feature_sha256':source_features, 'rig':rig,
            'cam_from_rig':[{'rotation':r.tolist(),'translation':t.tolist()} for r,t in ext], 'frames':results}
    data=(json.dumps(report,indent=2,allow_nan=False)+'\n').encode()
    if len(data)>5_000_000: raise ValueError('Report exceeds 5 MB')
    with output.open('xb') as f: f.write(data)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('model','workspace','selection','new-features','feature-manifest','input-manifest','anchor-manifest','seed','output'):
        parser.add_argument('--'+name, required=True, type=Path)
    args=parser.parse_args()
    report=register(args.model,args.workspace,args.selection,args.new_features,args.feature_manifest,args.input_manifest,args.anchor_manifest,args.seed,args.output)
    print(f"Accepted {sum(r['accepted'] for r in report['frames'])}/{len(report['frames'])}; report: {args.output}")


if __name__=='__main__': main()
