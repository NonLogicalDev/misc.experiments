#!/usr/bin/env python3
"""Propagate sparse SAM masks through full ERP frames; results require review."""
import argparse
import hashlib
import json
from pathlib import Path
import time

import cv2
import numpy as np
from warp_sequence import spherical_guard


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def flow(source, target):
    """Destination-to-source flow; duplicated longitudes give seam context."""
    h, w = source.shape
    size = (w // 2, h // 2)
    a = cv2.resize(target, size, interpolation=cv2.INTER_AREA)
    b = cv2.resize(source, size, interpolation=cv2.INTER_AREA)
    a = np.tile(a, (1, 3)); b = np.tile(b, (1, 3))
    displacement = cv2.calcOpticalFlowFarneback(a, b, None, .5, 3, 15, 3, 5, 1.2, 0)
    displacement = displacement[:, size[0]:2 * size[0]]
    return cv2.resize(displacement, (w, h), interpolation=cv2.INTER_LINEAR) * 2


def remap(image, displacement, interpolation=cv2.INTER_NEAREST):
    h, w = image.shape[:2]
    x, y = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    # Reflect through a pole and rotate longitude by half a turn. Padding
    # provides correct bilinear neighbors at the pole and longitude seam.
    v = np.mod(y + displacement[..., 1] + .5, 2*h)
    reflected = v >= h
    my = np.where(reflected, 2*h-v, v) - .5 + 1
    mx = np.mod(x + displacement[..., 0] + reflected*(w//2), w) + 1
    top = np.roll(image[:1], w//2, axis=1)
    bottom = np.roll(image[-1:], w//2, axis=1)
    vertical = np.concatenate((top, image, bottom), axis=0)
    padded = np.concatenate((vertical[:, -1:], vertical, vertical[:, :1]), axis=1)
    return cv2.remap(padded, mx.astype(np.float32), my.astype(np.float32), interpolation,
                     borderMode=cv2.BORDER_CONSTANT, borderValue=255)


def consistent(reverse, forward, threshold=2.0):
    back = remap(forward, reverse, cv2.INTER_LINEAR)
    h, w = reverse.shape[:2]
    y = np.arange(h, dtype=np.float32)[:, None] + reverse[..., 1]
    return (np.linalg.norm(reverse + back, axis=2) <= threshold) & (y >= 0) & (y < h - 1)


def run(frames_dir, masks_dir, source_manifest, output, key_stride, guard, max_frames, fusion="union"):
    if fusion not in ("union", "nearest-consistent"):
        raise ValueError("Unknown fusion policy")
    started = time.monotonic()
    records = json.loads(source_manifest.read_text())['frames']
    if len(records) < 2 or len(records) > max_frames or key_stride < 1 or (len(records)-1) % key_stride:
        raise ValueError('Frames must fit max-frames and end on a keyframe')
    if output.exists(): raise FileExistsError(output)
    output.mkdir(parents=True)
    (output/'INCOMPLETE').write_text('Propagation incomplete\n')
    frames, masks = [], []
    for i in range(len(records)):
        fp = frames_dir / f'frame_{i:05d}.png'; mp = masks_dir / f'frame_{i:05d}.png'
        image = cv2.imread(str(fp), cv2.IMREAD_GRAYSCALE)
        mask = cv2.imread(str(mp), cv2.IMREAD_GRAYSCALE) if mp.exists() else None
        if image is None or image.shape[1] != image.shape[0]*2 or (mask is None and i % key_stride == 0) or (mask is not None and image.shape != mask.shape):
            raise ValueError(f'Invalid input or missing keyframe mask at ordinal {i}')
        frames.append(image); masks.append(None if mask is None else np.where(mask < 128, 255, 0).astype(np.uint8))
    candidates = {i: masks[i].copy() for i in range(0, len(records), key_stride)}
    uncertainty = {}
    for start in range(0, len(records)-1, key_stride):
        end = start + key_stride
        # Each adjacent pair is checked both ways; no view extraction.
        toward_prev, toward_next = {}, {}
        for i in range(start, end):
            toward_prev[i+1] = flow(frames[i], frames[i+1])
            toward_next[i] = flow(frames[i+1], frames[i])
        left, right = masks[start].copy(), masks[end].copy()
        lefts, rights, low_left, low_right = {}, {}, {}, {}
        for i in range(start+1, end):
            v = toward_prev[i]; left = remap(left, v)
            lefts[i] = left.copy(); low_left[i] = ~consistent(v, toward_next[i-1])
        for i in range(end-1, start, -1):
            v = toward_next[i]; right = remap(right, v)
            rights[i] = right.copy(); low_right[i] = ~consistent(v, toward_prev[i+1])
        for i in range(start+1, end):
            union = cv2.bitwise_or(lefts[i], rights[i])
            # Prefer the closer key's propagation only where its local
            # forward/backward flow is consistent; fall back to the union.
            # This heuristic can miss a limb when confidence is misleading.
            if fusion == "nearest-consistent":
                preferred, uncertain = ((lefts[i], low_left[i]) if i-start <= end-i else (rights[i], low_right[i]))
                fused = np.where(uncertain, union, preferred).astype(np.uint8)
            else:
                fused = union
            nearby = spherical_guard(fused, guard)
            low = low_left[i] | low_right[i] | (lefts[i] != rights[i])
            uncertain_region = np.where((nearby > 0) & low, 255, 0).astype(np.uint8)
            candidates[i] = cv2.bitwise_or(nearby, spherical_guard(uncertain_region, guard))
            uncertainty[i] = float(low.mean())
    stats = []
    for i, record in enumerate(records):
        exclude = candidates[i]; reference = masks[i]
        name = f'frame_{record["source_frame"]:06d}.png'
        if not cv2.imwrite(str(output/name), 255-exclude): raise OSError(name)
        fn = None if reference is None else int(np.count_nonzero((reference > 0) & (exclude == 0)))
        fp = None if reference is None else int(np.count_nonzero((reference == 0) & (exclude > 0)))
        stats.append({'source_frame':record['source_frame'], 'video_pts_s':record['video_pts_s'], 'mask':name,
                      'is_keyframe':i % key_stride == 0, 'sam_reference_excluded_pixels':None if reference is None else int(np.count_nonzero(reference)),
                      'candidate_excluded_pixels':int(np.count_nonzero(exclude)), 'sam_excluded_candidate_kept_pixels':fn,
                      'sam_kept_candidate_excluded_pixels':fp, 'low_consistency_or_disagreement_fraction':uncertainty.get(i,0),
                      'source_image_sha256':digest(frames_dir/f'frame_{i:05d}.png'),
                      'sam_mask_sha256':None if reference is None else digest(masks_dir/f'frame_{i:05d}.png'), 'candidate_sha256':digest(output/name)})
    manifest={'warning':'UNREVIEWED candidates; SAM comparison is not ground truth; visible review required',
              'coordinate_system':'camera-relative full ERP', 'mask_convention':'white keep black exclude',
              'method':'bidirectional Farneback with longitude wrap; selected fusion, flow consistency and spherical guard',
              'key_stride':key_stride, 'guard_pixels':guard, 'fusion':fusion, 'elapsed_seconds':time.monotonic()-started,
              'source_manifest_sha256':digest(source_manifest), 'frames':stats}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    (output/'INCOMPLETE').unlink()
    return manifest


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('frames','sam_masks','source_manifest','output'): p.add_argument(name, type=Path)
    p.add_argument('--fusion',choices=('union','nearest-consistent'),default='union');p.add_argument('--key-stride',type=int,default=3);p.add_argument('--guard',type=int,default=8);p.add_argument('--max-frames',type=int,required=True)
    a=p.parse_args();run(a.frames,a.sam_masks,a.source_manifest,a.output,a.key_stride,a.guard,a.max_frames,a.fusion)


if __name__ == '__main__': main()
