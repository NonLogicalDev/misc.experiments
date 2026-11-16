"""Fit one inter-lens rotation from full camera-frame ERP observations.

Inputs are independently projected fisheye observations, never perspective crops.
The fitted matrix maps lens 1 nominal rays to lens 0 nominal rays. Sampling lens 1
for an output ray therefore uses its transpose before the embedded calibration.
"""
import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
from scipy.spatial.transform import Rotation


def rays(points, width, height):
    points = np.asarray(points, dtype=float)
    lon = (points[:, 0] + .5) * (2 * np.pi / width)
    lat = np.pi / 2 - (points[:, 1] + .5) * (np.pi / height)
    return np.column_stack((np.cos(lat)*np.cos(lon), -np.cos(lat)*np.sin(lon), np.sin(lat)))


def wahba(source, target, weights=None):
    weights = np.ones(len(source)) if weights is None else weights
    u, _, vt = np.linalg.svd((source * weights[:, None]).T @ target)
    correction = np.eye(3)
    correction[2, 2] = np.linalg.det(vt.T @ u.T)
    return vt.T @ correction @ u.T


def errors(source, target, rotation):
    return np.rad2deg(np.arctan2(np.linalg.norm(np.cross(source @ rotation.T, target), axis=1), np.einsum('ij,ij->i', source @ rotation.T, target)))


def robust_fit(source, target, threshold=.5, trials=2000, seed=42):
    if len(source) < 12:
        raise ValueError('Need at least twelve correspondences')
    rng = np.random.default_rng(seed)
    best = None
    score = (-1, -np.inf)
    for _ in range(trials):
        indices = rng.choice(len(source), 3, replace=False)
        rotation = wahba(source[indices], target[indices])
        residual = errors(source, target, rotation)
        mask = residual < threshold
        candidate = (int(mask.sum()), -float(np.minimum(residual, threshold).sum()))
        if candidate > score:
            best, score = mask, candidate
    if best.sum() < 12:
        raise ValueError('Insufficient consensus for a fixed rotation')
    rotation = wahba(source[best], target[best])
    for _ in range(8):
        residual = errors(source, target, rotation)
        weights = np.square(np.maximum(0, 1 - np.square(residual / threshold)))
        rotation = wahba(source, target, weights)
    return rotation, errors(source, target, rotation) < threshold


def matches(first, second, mask0, mask1):
    if first.shape != second.shape or mask0.shape != first.shape[:2] or mask1.shape != first.shape[:2]:
        raise ValueError('Images and masks must have identical dimensions')
    detector = cv2.SIFT_create(nfeatures=16000, contrastThreshold=.025)
    def describe(image, mask):
        mask = (mask > 127).astype(np.uint8)*255
        mask[:6] = 0; mask[-6:] = 0; mask[:, :6] = 0; mask[:, -6:] = 0
        clearance = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
        keys, desc = detector.detectAndCompute(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), mask)
        keep = [i for i,k in enumerate(keys) if clearance[round(k.pt[1]), round(k.pt[0])] > max(6, 2*k.size)]
        return [keys[i] for i in keep], desc[keep] if desc is not None else None
    k0, d0 = describe(first, mask0); k1, d1 = describe(second, mask1)
    if d0 is None or d1 is None or len(d0)<2 or len(d1)<2:
        return np.empty((0,2)), np.empty((0,2))
    matcher = cv2.BFMatcher()
    def ratio(a,b):
        return {pair[0].queryIdx:pair[0].trainIdx for pair in matcher.knnMatch(a,b,k=2) if len(pair)==2 and pair[0].distance < .72*pair[1].distance}
    forward, backward = ratio(d0,d1), ratio(d1,d0)
    pairs = [(i,j) for i,j in forward.items() if backward.get(j)==i]
    return np.array([k0[i].pt for i,j in pairs]).reshape(-1,2), np.array([k1[j].pt for i,j in pairs]).reshape(-1,2)


def summary(values):
    return {'count':len(values), 'median_degrees':float(np.median(values)), 'p90_degrees':float(np.percentile(values,90)), 'p95_degrees':float(np.percentile(values,95))} if len(values) else {'count':0}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest',type=Path); parser.add_argument('output',type=Path)
    parser.add_argument('--threshold-degrees',type=float,default=.5)
    args=parser.parse_args()
    if args.output.exists(): parser.error('Output must be new')
    manifest=json.loads(args.manifest.read_text())
    frames=manifest['frames']; collected=[]
    for frame in frames:
        if frame['split'] not in ('train','validation'): raise ValueError('Explicit train/validation split required')
        paths={name:args.manifest.parent/frame[name] for name in ('lens0','lens1','mask0','mask1')}
        loaded={name:cv2.imread(str(path),cv2.IMREAD_GRAYSCALE if name.startswith('mask') else cv2.IMREAD_COLOR) for name,path in paths.items()}
        if any(image is None for image in loaded.values()): raise ValueError('Cannot read frame inputs')
        p0,p1=matches(loaded['lens0'],loaded['lens1'],loaded['mask0'],loaded['mask1'])
        h,w=loaded['lens0'].shape[:2]
        a,b=rays(p1,w,h),rays(p0,w,h)
        keep=errors(a,b,np.eye(3))<8
        collected.append((frame,a[keep],b[keep],p0[keep],p1[keep]))
        print(f"Frame {frame['frame']}: {keep.sum()} mutual matches ({frame['split']})",flush=True)
    train=[item for item in collected if item[0]['split']=='train']
    valid=[item for item in collected if item[0]['split']=='validation']
    if not train or not valid: raise ValueError('Need both training and held-out frames')
    source=np.concatenate([item[1] for item in train]); target=np.concatenate([item[2] for item in train])
    rotation, inliers=robust_fit(source,target,args.threshold_degrees)
    records=[]
    for frame,a,b,p0,p1 in collected:
        before=errors(a,b,np.eye(3));after=errors(a,b,rotation)
        records.append({'frame':frame['frame'],'split':frame['split'],'before':summary(before),'after':summary(after),'consensus_count':int((after<args.threshold_degrees).sum()),'points0':p0.tolist(),'points1':p1.tolist(),'before_degrees':before.tolist(),'after_degrees':after.tolist()})
    va=np.concatenate([item[1] for item in valid]); vb=np.concatenate([item[2] for item in valid])
    result={'input_manifest':str(args.manifest.resolve()),'input_sha256':hashlib.sha256(args.manifest.read_bytes()).hexdigest(),'mapping':'lens1 nominal camera ray -> lens0 nominal camera ray; sample lens1 at transpose(rotation) times output camera ray','rotation_matrix':rotation.tolist(),'quaternion_xyzw':Rotation.from_matrix(rotation).as_quat().tolist(),'rotation_degrees':float(np.rad2deg(Rotation.from_matrix(rotation).magnitude())),'threshold_degrees':args.threshold_degrees,'training_consensus':int(inliers.sum()),'training_total':len(source),'validation_before':summary(errors(va,vb,np.eye(3))),'validation_after':summary(errors(va,vb,rotation)),'frames':records}
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='frames'},indent=2))

if __name__=='__main__': main()
