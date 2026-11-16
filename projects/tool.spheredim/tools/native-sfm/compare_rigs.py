#!/usr/bin/env python3
"""Compare two COLMAP ERP reconstructions on held-out SIFT tracks.

Inputs are identically named paired frames under cam0/ and cam1/. White masks
select held-out pixels; white feature masks select SfM features. This program
requires those masks to be disjoint and checks evaluation descriptors against
the feature-mask boundary. SfM descriptor support must be audited separately;
disjoint keypoint masks alone do not prove pixel independence.
"""
import argparse
import collections
import hashlib
import json
import math
import struct
from pathlib import Path

import cv2
import numpy as np


def rotation(q):
    q = np.asarray(q, dtype=float)
    q /= np.linalg.norm(q)
    w, x, y, z = q
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                     [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                     [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])


def read_poses(model):
    path = Path(model) / 'images.txt'
    if not path.exists():
        return read_binary_poses(Path(model) / 'images.bin')
    lines = path.read_text().splitlines()
    result = {}
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1
        if not line or line.startswith('#'):
            continue
        fields = line.split()
        if len(fields) < 10:
            raise ValueError(f'Invalid COLMAP image header in {path}: {line}')
        R = rotation([float(x) for x in fields[1:5]])
        t = np.array([float(x) for x in fields[5:8]])
        result[fields[9]] = (R, -R.T @ t)
        if i >= len(lines):
            raise ValueError(f'Missing points line for {fields[9]}')
        i += 1
    if not result:
        raise ValueError(f'No poses in {path}')
    return result



def read_binary_poses(path):
    result = {}
    with path.open('rb') as f:
        def read_exact(n):
            data = f.read(n)
            if len(data) != n:
                raise ValueError(f'Truncated COLMAP image file: {path}')
            return data
        count = struct.unpack('<Q', read_exact(8))[0]
        for _ in range(count):
            row = struct.unpack('<i7di', read_exact(64))
            name_bytes = bytearray()
            while True:
                ch = read_exact(1)
                if ch == b'\0': break
                name_bytes.extend(ch)
                if len(name_bytes) > 65536: raise ValueError('Invalid COLMAP image name')
            name = name_bytes.decode('utf-8')
            R = rotation(row[1:5]); t = np.asarray(row[5:8])
            if name in result: raise ValueError(f'Duplicate image: {name}')
            result[name] = (R, -R.T @ t)
            n = struct.unpack('<Q',read_exact(8))[0]
            # Consume records rather than seeking beyond EOF unnoticed.
            for _ in range(n): read_exact(24)
        if not result: raise ValueError(f'No poses in {path}')
    return result


def model_image_file(model):
    text = model / 'images.txt'
    return text if text.exists() else model / 'images.bin'

def ray(x, y, width, height):
    theta = (x / width - .5) * 2 * np.pi
    phi = (.5 - y / height) * np.pi
    return np.array([np.sin(theta)*np.cos(phi), -np.sin(phi), np.cos(theta)*np.cos(phi)])


def triangulate(a, b, min_angle=0.2):
    c0, d0 = a
    c1, d1 = b
    dot = np.clip(np.dot(d0, d1), -1, 1)
    angle = math.degrees(math.acos(abs(dot)))
    if angle < min_angle or np.linalg.norm(c1-c0) < 1e-9:
        return None, 'degenerate'
    A = np.column_stack((d0, -d1))
    v, _, _, _ = np.linalg.lstsq(A, c1-c0, rcond=None)
    if min(v) <= 0:
        return None, 'negative'
    return (c0 + v[0]*d0 + c1 + v[1]*d1)*.5, None


def score_track(track, poses, width, height):
    selected = [o for o in track if o[0] in poses]
    if len({o[1] for o in selected}) < 3:
        return None, 'coverage'
    selected.sort(key=lambda o: (o[1], o[0]))
    ends = (selected[0], selected[-1])
    lines = []
    for name, _, x, y in ends:
        R, C = poses[name]
        lines.append((C, R.T @ ray(x, y, width, height)))
    point, reason = triangulate(*lines)
    if reason:
        return None, reason
    errors = []
    for name, _, x, y in selected[1:-1]:
        R, C = poses[name]
        pred = R @ (point-C)
        if np.linalg.norm(pred) < 1e-12:
            return None, 'degenerate'
        measured = ray(x, y, width, height)
        errors.append(math.acos(float(np.clip(np.dot(pred/np.linalg.norm(pred), measured), -1, 1))) * width/(2*math.pi))
    return errors, None


def summary(errors):
    if not errors:
        return {'count': 0}
    v = np.asarray(errors)
    return {'count': len(errors), 'median': float(np.median(v)), 'p90': float(np.percentile(v,90)),
            'p95': float(np.percentile(v,95)), 'rms': float(np.sqrt(np.mean(v*v)))}


def rig_stats(poses):
    pairs = []
    for name in sorted(poses):
        if not name.startswith('cam0/'):
            continue
        other = 'cam1/' + name[5:]
        if other not in poses:
            continue
        R0, C0 = poses[name]; R1, C1 = poses[other]
        pairs.append((np.linalg.norm(C1-C0), R1 @ R0.T))
    if not pairs:
        return {'paired_bodies': 0}
    base = pairs[0][1]
    angles = [math.degrees(math.acos(float(np.clip((np.trace(R @ base.T)-1)/2, -1, 1)))) for _, R in pairs]
    lengths = [float(p[0]) for p in pairs]
    return {'paired_bodies': len(pairs), 'baseline_min': min(lengths), 'baseline_max': max(lengths),
            'relative_rotation_max_deviation_degrees': max(angles)}


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()



def essential_inliers(bearings_a, bearings_b, threshold=1.5/ (1024/(2*math.pi)), trials=512, seed=19):
    """Fit a spherical essential matrix without using either reconstructed model."""
    a = np.asarray(bearings_a, dtype=float)
    b = np.asarray(bearings_b, dtype=float)
    n = len(a)
    if a.shape != (n,3) or b.shape != (n,3) or n < 12:
        return np.zeros(n, dtype=bool)
    design = np.einsum('ni,nj->nij', b, a).reshape(n,9)
    rng = np.random.default_rng(seed)
    best = np.zeros(n,dtype=bool)
    def fit(indices):
        matrix = design[indices]
        if np.linalg.matrix_rank(matrix, tol=1e-10) < 8: return None
        _, _, v = np.linalg.svd(matrix, full_matrices=True)
        E = v[-1].reshape(3,3)
        u, singular, vt = np.linalg.svd(E)
        if singular[1] < 1e-10: return None
        return u @ np.diag([(singular[0]+singular[1])/2]*2+[0.]) @ vt
    def inliers(E):
        ea = a @ E.T; etb = b @ E
        denom = np.sqrt(np.sum(ea*ea,axis=1)+np.sum(etb*etb,axis=1))
        residual = np.full(n,np.inf)
        np.divide(np.abs(np.sum(b*ea,axis=1)),denom,out=residual,where=denom>1e-12)
        return residual < threshold
    for _ in range(trials):
        E=fit(rng.choice(n,8,replace=False))
        if E is not None:
            mask=inliers(E)
            if mask.sum()>best.sum(): best=mask
    if best.sum()<12: return np.zeros(n,dtype=bool)
    refined=fit(np.flatnonzero(best))
    if refined is not None:
        mask=inliers(refined)
        if mask.sum() >= best.sum(): best=mask
    return best

def tracks_from_images(images, evaluation, training, margin):
    paths = sorted(p for cam in ('cam0','cam1') for p in (images/cam).glob('*.png'))
    if not paths or len(paths)>32:
        raise ValueError('Expected 1–32 paired PNG images')
    stems = sorted({p.stem for p in paths})
    if any(not (images/cam/(s+'.png')).exists() for cam in ('cam0','cam1') for s in stems):
        raise ValueError('Images must be complete synchronized pairs')
    index = {s:i for i,s in enumerate(stems)}
    records = []; inputs = []; shape = None
    sift = cv2.SIFT_create(nfeatures=0, contrastThreshold=0.01)
    for p in paths:
        name = p.relative_to(images).as_posix()
        ep, tp = evaluation/name, training/name
        img = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
        em = cv2.imread(str(ep), cv2.IMREAD_GRAYSCALE)
        tm = cv2.imread(str(tp), cv2.IMREAD_GRAYSCALE)
        if img is None or em is None or tm is None or img.shape != em.shape or img.shape != tm.shape:
            raise ValueError(f'Missing or mismatched image/masks: {name}')
        if shape is None: shape = img.shape
        if img.shape != shape or img.shape[1] != img.shape[0]*2 or img.shape[1] > 1024:
            raise ValueError('Expected matching ERP frames at most 1024x512')
        if np.any((em > 0) & (tm > 0)):
            raise ValueError(f'Evaluation and feature masks overlap: {name}')
        valid = (em>0).astype(np.uint8)*255
        kp, desc = sift.detectAndCompute(img, valid)
        # Keep the evaluation descriptor footprint away from training feature centers.
        dist = cv2.distanceTransform((tm==0).astype(np.uint8), cv2.DIST_L2, 5)
        keep = [i for i,k in enumerate(kp) if dist[min(int(round(k.pt[1])),img.shape[0]-1),min(int(round(k.pt[0])),img.shape[1]-1)] >= max(margin, 6*k.size)]
        desc = desc[keep] if desc is not None and keep else None
        records.append((name,index[p.stem],[kp[i] for i in keep],desc))
        inputs.append({'name':name,'image_sha256':digest(p),'evaluation_mask_sha256':digest(ep),'feature_mask_sha256':digest(tp),'keypoints':len(keep)})
    parent = {}; members = {}
    def find(x):
        parent.setdefault(x,x); members.setdefault(x,{x[0]})
        if parent[x] != x: parent[x] = find(parent[x])
        return parent[x]
    edges = []
    matcher = cv2.BFMatcher(cv2.NORM_L2)
    for a in range(len(records)):
        for b in range(a+1,len(records)):
            na, ta, _, da = records[a]; nb, tb, _, db = records[b]
            if abs(ta-tb)>3 or (ta==tb and na[:4]==nb[:4]) or da is None or db is None or len(da)<2 or len(db)<2: continue
            ab=matcher.knnMatch(da,db,k=2); ba=matcher.knnMatch(db,da,k=2)
            reverse={m.queryIdx:m.trainIdx for pair in ba if len(pair)==2 for m,n in [pair] if m.distance < .75*n.distance}
            candidates=[]
            for pair in ab:
                if len(pair)!=2: continue
                m,n=pair
                if m.distance < .75*n.distance and reverse.get(m.trainIdx)==m.queryIdx:
                    candidates.append(m)
            if len(candidates)<12: continue
            ka,kb=records[a][2],records[b][2]
            rays_a=np.array([ray(*ka[m.queryIdx].pt,shape[1],shape[0]) for m in candidates])
            rays_b=np.array([ray(*kb[m.trainIdx].pt,shape[1],shape[0]) for m in candidates])
            inlier=essential_inliers(rays_a,rays_b,threshold=1.5/(shape[1]/(2*math.pi)))
            for m,keep in zip(candidates,inlier):
                if keep: edges.append((float(m.distance),(a,m.queryIdx),(b,m.trainIdx)))
    for _,a,b in sorted(edges):
        ra,rb=find(a),find(b)
        if ra!=rb and not (members[ra] & members[rb]):
            parent[rb]=ra; members[ra] |= members[rb]
    groups={}
    for node in list(parent): groups.setdefault(find(node),[]).append(node)
    tracks=[]
    for nodes in groups.values():
        obs=[(records[i][0],records[i][1],*records[i][2][j].pt) for i,j in nodes]
        if len({o[1] for o in obs})>=3: tracks.append(obs)
    return tracks, shape, inputs


def compare(tracks, poses_a, poses_b, width, height):
    errors = [[],[]]; shared = [[],[]]; reasons = [{},{}]
    groups = [collections.defaultdict(list), collections.defaultdict(list)]
    group_tracks = collections.defaultdict(set)
    for track_id,track in enumerate(tracks):
        # Raw uses each model's coverage; shared fixes the same observations and endpoints.
        common = [o for o in track if o[0] in poses_a and o[0] in poses_b]
        vals=[]
        for i,poses in enumerate((poses_a,poses_b)):
            value, reason = score_track(track,poses,width,height)
            if reason: reasons[i][reason]=reasons[i].get(reason,0)+1
            else: errors[i].extend(value)
            vals.append(score_track(common,poses,width,height)[0])
        if all(v is not None for v in vals):
            shared[0].extend(vals[0]); shared[1].extend(vals[1])
            ordered=sorted(common,key=lambda o:(o[1],o[0]))[1:-1]
            for observation, va, vb in zip(ordered,*vals):
                name=observation[0]
                for key in ('lens/'+name.split('/')[0], 'frame/'+Path(name).name):
                    groups[0][key].append(va); groups[1][key].append(vb)
                    group_tracks[key].add(track_id)
    return [{'raw':summary(errors[i]),'shared_valid':summary(shared[i]),'excluded_tracks':reasons[i],
             'registered_images':len(p),'rig':rig_stats(p),
             'shared_by_lens_and_frame':{k:{**summary(v),'tracks':len(group_tracks[k])} for k,v in groups[i].items()}} for i,p in enumerate((poses_a,poses_b))]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--images',type=Path,required=True); p.add_argument('--eval-masks',type=Path,required=True)
    p.add_argument('--feature-masks',type=Path,required=True); p.add_argument('--model-a',type=Path,required=True)
    p.add_argument('--model-b',type=Path,required=True); p.add_argument('--output',type=Path,required=True)
    p.add_argument('--margin',type=int,default=16)
    a=p.parse_args()
    if a.margin < 1: p.error('margin must be positive')
    tracks,shape,inputs=tracks_from_images(a.images,a.eval_masks,a.feature_masks,a.margin)
    if not tracks:
        raise ValueError('No held-out tracks span three timestamps')
    manifest = a.images.parent / 'manifest.json'
    report={'method':'held-out native ERP SIFT; pose-independent spherical essential RANSAC; endpoint ray triangulation, no image alignment',
            'dataset_manifest_sha256':digest(manifest) if manifest.exists() else None,
            'evaluator_sha256':digest(Path(__file__)),
            'verification':{'model':'spherical essential matrix','trials':512,'seed':19,
                            'min_pair_inliers':12,'threshold_erp_pixels':1.5,
                            'note':'uses held-out pair correspondences, not either SfM model'},
            'mask_requirement':'disjoint feature-center masks; eval descriptor support guarded; SfM descriptor support requires independent verification',
            'image_shape':list(shape),'inputs':inputs,'tracks':len(tracks),
            'track_observations':tracks,'opencv_version':cv2.__version__,
            'models':[{'path':str(x.resolve()),'poses_file':model_image_file(x).name,'poses_sha256':digest(model_image_file(x))} for x in (a.model_a,a.model_b)],
            'results':compare(tracks,read_poses(a.model_a),read_poses(a.model_b),shape[1],shape[0])}
    a.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'tracks':len(tracks),'results':report['results']},indent=2))

if __name__=='__main__': main()
