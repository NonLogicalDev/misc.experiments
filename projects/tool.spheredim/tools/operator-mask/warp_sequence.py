#!/usr/bin/env python3
"""Warp per-frame SAM masks from camera coordinates to FlowState panorama coordinates.

SAM input PNGs use white=keep and black=exclude. Source frames must be uniformly
sampled from the same recording as the orientation CSV. Output also uses
white=keep. This tool transforms masks; it does not validate person coverage.
"""
import argparse
import csv
import json
from pathlib import Path

import cv2
import numpy as np
from scipy.spatial.transform import Rotation


def spherical_guard(exclude, radius):
    """Dilate across the seam and reflect across each pole with a half-turn."""
    h, w = exclude.shape
    if w % 2 or radius < 0 or radius >= h:
        raise ValueError('width must be even and guard must be in [0, height)')
    if not radius:
        return exclude.copy()
    yy = np.arange(-radius, h + radius)
    pole = (yy < 0) | (yy >= h)
    yy = np.where(yy < 0, -yy - 1, np.where(yy >= h, 2*h - yy - 1, yy))
    xx = np.arange(-radius, w + radius)[None, :] + pole[:, None] * (w // 2)
    padded = exclude[yy[:, None], xx % w]
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2*radius+1, 2*radius+1))
    return cv2.dilate(padded, kernel)[radius:radius+h, radius:radius+w]


def warp(exclude, rotation):
    """Sample camera-coordinate exclude mask at FlowState output rays."""
    h, w = exclude.shape
    lon = (np.arange(w, dtype=np.float32) + .5) * (2*np.pi/w)
    lat = np.pi/2 - (np.arange(h, dtype=np.float32) + .5) * (np.pi/h)
    c = np.cos(lat)[:, None]
    x = c * np.cos(lon)[None, :]
    y = -c * np.sin(lon)[None, :]
    z = np.sin(lat)[:, None]
    sx = rotation[0,0]*x + rotation[0,1]*y + rotation[0,2]*z
    sy = rotation[1,0]*x + rotation[1,1]*y + rotation[1,2]*z
    sz = rotation[2,0]*x + rotation[2,1]*y + rotation[2,2]*z
    mx = (np.mod(np.arctan2(-sy, sx)*(w/(2*np.pi))-.5, w)+1).astype(np.float32)
    my = (np.arccos(np.clip(sz,-1,1))*(h/np.pi)-.5+1).astype(np.float32)
    # One-pixel spherical padding ensures bilinear samples across the longitude seam
    # and through the poles see the matching neighboring ray.
    yy = np.arange(-1,h+1)
    pole = (yy < 0) | (yy >= h)
    yy = np.where(yy < 0, -yy-1, np.where(yy >= h, 2*h-yy-1, yy))
    xx = (np.arange(-1,w+1)[None,:] + pole[:,None]*(w//2)) % w
    padded = exclude[yy[:,None],xx]
    sampled = cv2.remap(padded, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    # Any interpolated excluded pixel is excluded, preserving a conservative edge.
    return np.where(sampled > 0, 255, 0).astype(np.uint8)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('masks', type=Path, help='SAM sequence frame_00000.png, ...')
    parser.add_argument('orientations', type=Path, help='matching orientation_frames_fused.csv')
    parser.add_argument('output', type=Path, help='new directory for stabilized keep masks')
    parser.add_argument('--stride', type=int, required=True, help='source frame difference between successive masks')
    parser.add_argument('--first-frame', type=int, default=0)
    parser.add_argument('--guard', type=int, default=4, help='spherical dilation radius in input pixels')
    parser.add_argument('--output-guard', type=int, default=0, help='additional spherical dilation in stabilized output pixels')
    args = parser.parse_args()
    if args.stride < 1 or args.first_frame < 0:
        parser.error('stride must be positive and first frame nonnegative')
    files = sorted(args.masks.glob('frame_*.png'))
    if not files or any(f.name != f'frame_{i:05d}.png' for i,f in enumerate(files)):
        raise ValueError('input must start at frame_00000.png and have no gaps')
    with args.orientations.open(newline='') as handle:
        rows = list(csv.DictReader(handle))
    if any(int(row['frame']) != i for i,row in enumerate(rows)):
        raise ValueError('orientation CSV frame numbers must be contiguous from zero')
    if args.first_frame + (len(files)-1)*args.stride >= len(rows):
        raise ValueError('mask sequence exceeds orientation CSV')
    if args.output.exists():
        raise FileExistsError(f'output already exists: {args.output}')
    args.output.mkdir(parents=True)
    records = []
    dimensions = None
    for i,path in enumerate(files):
        image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if image is None: raise ValueError(f'cannot read {path}')
        if image.shape[1] != 2 * image.shape[0]: raise ValueError(f'expected a 2:1 equirectangular mask: {path}')
        if dimensions is None: dimensions = image.shape
        if image.shape != dimensions: raise ValueError(f'inconsistent size: {path}')
        source = args.first_frame + i*args.stride
        row = rows[source]
        q = [float(row[k]) for k in ('q_x','q_y','q_z','q_w')]
        rotation = Rotation.from_quat(q).as_matrix().T @ Rotation.from_euler('z',float(row['heading_rad'])).as_matrix()
        exclude = spherical_guard(np.where(image < 128,255,0).astype(np.uint8), args.guard)
        keep = 255 - spherical_guard(warp(exclude, rotation), args.output_guard)
        name = f'frame_{source:06d}.png'
        if not cv2.imwrite(str(args.output/name),keep): raise OSError(f'cannot write {name}')
        weights = np.sin(np.pi*(np.arange(image.shape[0])+.5)/image.shape[0])[:,None]
        excluded_fraction = float(((keep == 0)*weights).sum()/(weights.sum()*image.shape[1]))
        records.append({'source_frame':source,'video_pts_s':float(row['video_pts_s']),'mask':name,'excluded_solid_angle_fraction':excluded_fraction})
    (args.output/'manifest.json').write_text(json.dumps({'warning':'Unreviewed candidate masks; operator coverage is not guaranteed.','mask_convention':'white=keep, black=exclude','source_coordinate_system':'OFF camera-relative ERP','output_coordinate_system':'FlowState ERP, rolling shutter off','source_guard_pixels':args.guard,'output_guard_pixels':args.output_guard,'frames':records}, indent=2)+'\n')
    print(f'wrote {len(records)} candidate masks; review operator coverage before use')

if __name__ == '__main__': main()
