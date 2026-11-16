#!/usr/bin/env python3
"""Create two fixed-baseline hypotheses without changing the source rig or images."""
import argparse
import copy
import hashlib
import json
from pathlib import Path

import numpy as np

# Maps Spirula CV (right, down, forward) vectors to the exporter body frame.
BODY_FROM_CV = np.array([[0., 0., -1.], [1., 0., 0.], [0., -1., 0.]])


def quaternion_matrix(q):
    q = np.asarray(q, dtype=float)
    if q.shape != (4,) or not np.all(np.isfinite(q)) or np.linalg.norm(q) < 1e-12:
        raise ValueError('Invalid quaternion')
    w, x, y, z = q / np.linalg.norm(q)
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                     [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                     [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])


def derive(calibration, rig, fit):
    lenses = calibration['lenses']
    if len(lenses) != 2: raise ValueError('Expected exactly two metadata lenses')
    members = rig['rigs'][0]['members']
    if len(members) != 2 or [m['prefix'] for m in members] != ['cam0', 'cam1']:
        raise ValueError('Expected cam0 and cam1 rig members')
    ref, cam = members
    if not all(m.get('fixed') and m.get('refine') == 'none' for m in members):
        raise ValueError('Expected fixed rig extrinsics')
    if not np.allclose(ref['translation'], 0): raise ValueError('cam0 must be the rig origin')
    R = quaternion_matrix(cam['rotation'])
    q0 = lenses[0]['orientation']
    R0 = quaternion_matrix([q0['w'], q0['x'], q0['y'], q0['z']])
    raw = np.asarray(lenses[1]['translation'],float) - np.asarray(lenses[0]['translation'],float)
    if raw.shape != (3,) or not np.all(np.isfinite(raw)): raise ValueError('Invalid metadata translation')
    magnitude = float(np.linalg.norm(raw))
    if magnitude <= 1e-12: raise ValueError('Metadata baseline is zero')
    body = R0.T @ raw
    fit_direction = np.asarray(fit['baseline_direction'],float)
    if fit_direction.shape != (3,) or not np.all(np.isfinite(fit_direction)) or not np.isclose(np.linalg.norm(fit_direction),1,atol=1e-6):
        raise ValueError('Invalid fitted baseline direction')
    expected = -R @ BODY_FROM_CV.T @ fit_direction
    actual = np.asarray(cam['translation'],float)
    if not np.allclose(actual, expected, atol=1e-6):
        raise ValueError('Existing rig does not match the fitted direction and rotation')
    fitted = copy.deepcopy(rig); metadata = copy.deepcopy(rig)
    fitted['rigs'][0]['members'][1]['translation'] = (actual*magnitude).tolist()
    center_cv = BODY_FROM_CV.T @ body
    metadata['rigs'][0]['members'][1]['translation'] = (-R @ center_cv).tolist()
    angle = float(np.degrees(np.arccos(np.clip(np.dot(body/magnitude,fit_direction),-1,1))))
    return fitted, metadata, {'metadata_baseline_norm':magnitude,'metadata_center_body':body.tolist(),
                              'metadata_center_cv':center_cv.tolist(),
                              'angle_to_fitted_direction_degrees':angle}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--calibration',type=Path,required=True)
    parser.add_argument('--rig',type=Path,required=True)
    parser.add_argument('--fit',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    paths=(args.calibration,args.rig,args.fit)
    fitted,metadata,measurements=derive(*(json.loads(path.read_text()) for path in paths))
    out=args.output_dir
    outputs={'rig-fitted-metric.json':fitted,'rig-metadata.json':metadata}
    provenance={'inputs':{str(p.resolve()):sha(p) for p in paths}, **measurements,
        'assumptions':['Raw metadata translation difference is treated as lens1 camera center relative to lens0.',
                       'Lens0 orientation inverse maps that difference to the exporter body frame.',
                       'BODY_FROM_CV maps Spirula CV ray vectors to exporter body vectors; cam_from_rig translation is -R times center in CV.',
                       'Raw metadata translation unit and physical meaning are unverified. If meters, the norm is a meter baseline; otherwise the fitted-metric name is a hypothesis.'],
        'body_from_cv':BODY_FROM_CV.tolist(),
        'outputs_sha256':{name:hashlib.sha256((json.dumps(value,indent=2)+'\n').encode()).hexdigest() for name,value in outputs.items()}}
    outputs['rig-baseline-provenance.json']=provenance
    if not out.is_dir(): raise ValueError('Output directory must already exist')
    existing=[str(out/name) for name in outputs if (out/name).exists()]
    if existing: raise FileExistsError('Refusing to overwrite: '+', '.join(existing))
    for name,value in outputs.items():
        with (out/name).open('x') as f: json.dump(value,f,indent=2);f.write('\n')
    print(json.dumps(measurements,indent=2))

if __name__=='__main__': main()
