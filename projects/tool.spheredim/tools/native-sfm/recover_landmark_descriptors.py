#!/usr/bin/env python3
"""Recover descriptor rows linked to landmarks in a compacted native SfM model.

Inputs are the original workspace's matches.bin, features and sparse model. No
input is modified. The result is an in-memory API; callers decide what to save.
"""
import struct
from dataclasses import dataclass
from pathlib import Path


def read(f, fmt):
    size = struct.calcsize('<' + fmt)
    data = f.read(size)
    if len(data) != size:
        raise ValueError(f'Truncated input: {f.name}')
    return struct.unpack('<' + fmt, data)


def exact(f, size):
    data = f.read(size)
    if len(data) != size:
        raise ValueError(f'Truncated input: {f.name}')
    return data


@dataclass(frozen=True)
class Observation:
    image: str
    image_id: int
    compact_index: int
    feature_index: int
    xy: tuple
    scale: float
    orientation: float
    descriptor: bytes
    point_id: int
    xyz: tuple


def read_matches(path, names):
    with path.open('rb') as f:
        magic, version, count = read(f, '4sII')
        if magic != b'VKMT' or version != 5:
            raise ValueError('Expected VKMT version 5')
        images = []
        for _ in range(count):
            length, = read(f, 'I')
            name = exact(f, length).decode('utf-8')
            size, = read(f, 'I')
            images.append((name, size))
        if len({name for name, _ in images}) != count:
            raise ValueError('Duplicate matches image name')
        indices = {i: (name, size) for i, (name, size) in enumerate(images) if name in names}
        if {name for name, _ in indices.values()} != names:
            raise ValueError('Selected image missing from matches')
        used = {i: set() for i in indices}
        pairs, = read(f, 'I')
        for _ in range(pairs):
            a, b, _, n = read(f, 'IIiI')
            if a >= count or b >= count:
                raise ValueError('Invalid match image index')
            data = exact(f, n * 8)
            if a in used or b in used:
                for x, y in struct.iter_unpack('<II', data):
                    if x >= images[a][1] or y >= images[b][1]:
                        raise ValueError('Invalid match feature index')
                    if a in used:
                        used[a].add(x)
                    if b in used:
                        used[b].add(y)
        return {name: (size, sorted(used[i])) for i, (name, size) in indices.items()}


def read_features(path, expected_count):
    with path.open('rb') as f:
        magic, version, width, height, count, dim, dtype = read(f, '4s6I')
        if magic != b'VKFT' or version != 6 or not width or not height or count != expected_count:
            raise ValueError(f'Invalid feature header: {path}')
        if dtype != 0 or dim != 128:
            raise ValueError(f'Expected 128-byte SIFT descriptors: {path}')
        keypoints = list(struct.iter_unpack('<4f', exact(f, count * 16)))
        descriptors = exact(f, count * dim)
        return keypoints, descriptors, dim


def read_images(path, names):
    result = {}
    with path.open('rb') as f:
        count, = read(f, 'Q')
        for _ in range(count):
            row = read(f, 'i7di')
            name = bytearray()
            while True:
                char = exact(f, 1)
                if char == b'\0':
                    break
                name.extend(char)
                if len(name) > 65536:
                    raise ValueError('Invalid model image name')
            name = name.decode('utf-8')
            n, = read(f, 'Q')
            if name in names:
                if name in result:
                    raise ValueError('Duplicate model image')
                result[name] = (row[0], list(struct.iter_unpack('<ddq', exact(f, n * 24))))
            else:
                exact(f, n * 24)
        if f.read(1):
            raise ValueError('Trailing model image bytes')
    if set(result) != names:
        raise ValueError('Selected image missing from model')
    return result


def recover(model_dir, workspace_dir, image_names):
    """Return indexed observations after validating coordinates and point tracks.

    Image names include their image extension, as in COLMAP images.bin. The
    feature stem, including folders, must match the original VKMT image name.
    """
    model_dir, workspace_dir = Path(model_dir), Path(workspace_dir)
    image_names = list(image_names)
    if not image_names or len(set(image_names)) != len(image_names):
        raise ValueError('Select one or more unique images')
    stems = {str(Path(name).with_suffix('')) for name in image_names}
    if len(stems) != len(image_names) or any(Path(name).is_absolute() or '..' in Path(name).parts for name in image_names):
        raise ValueError('Invalid or ambiguous image name')
    mapping = read_matches(workspace_dir / 'matches.bin', stems)
    images = read_images(model_dir / 'images.bin', set(image_names))
    pending = {}
    for name in image_names:
        stem = str(Path(name).with_suffix(''))
        total, indices = mapping[stem]
        keypoints, descriptors, dim = read_features(workspace_dir / 'features' / (stem + '.bin'), total)
        image_id, rows = images[name]
        if len(indices) != len(rows):
            raise ValueError(f'Compacted feature count mismatch: {name}')
        for compact, (feature, (x, y, point_id)) in enumerate(zip(indices, rows)):
            k = keypoints[feature]
            if (x, y) != k[:2]:
                raise ValueError(f'Feature coordinate mismatch: {name} row {compact}')
            if point_id >= 0:
                key = (image_id, compact)
                pending[key] = (name, feature, k, descriptors[feature * dim:(feature + 1) * dim], point_id)
    points = {}
    seen = set()
    with (model_dir / 'points3D.bin').open('rb') as f:
        count, = read(f, 'Q')
        for _ in range(count):
            row = read(f, 'Q3d3BdQ')
            point_id, xyz, length = row[0], row[1:4], row[-1]
            if point_id in points:
                raise ValueError('Duplicate point ID')
            points[point_id] = xyz
            for image_id, index in struct.iter_unpack('<II', exact(f, length * 8)):
                key = (image_id, index)
                if key in pending:
                    if key in seen or pending[key][-1] != point_id:
                        raise ValueError('Point track does not match image observation')
                    seen.add(key)
        if f.read(1):
            raise ValueError('Trailing model point bytes')
    if seen != set(pending):
        raise ValueError('Missing reciprocal point track')
    out = []
    for (image_id, compact), (name, feature, k, descriptor, point_id) in pending.items():
        out.append(Observation(name, image_id, compact, feature, k[:2], k[2], k[3], descriptor, point_id, points[point_id]))
    return out
