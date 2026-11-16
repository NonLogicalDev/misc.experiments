#!/usr/bin/env python3
"""Inspect source crops around training-only SfM points shared across requested views."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import time
from pathlib import Path
import cv2
import numpy as np
import compare_density_models as modelio
from audit_seed_gauge import read_erp_cameras


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            digest.update(block)
    return digest.hexdigest()


def summarize_landmarks(points, frames):
    counts = Counter(len(views) for views in points.values())
    common = sorted(point for point, views in points.items() if len(views) == len(frames))
    if not points:
        conclusion = 'No tracked landmarks were available in the requested views; no ranking was computed.'
    elif not common:
        conclusion = 'No landmark spans all requested views; no across-view sharpness ranking was computed.'
    else:
        conclusion = f'{len(common)} landmarks span all requested views; crops are descriptive and no sharpness ranking was computed.'
    return counts, common, conclusion


def audit(model, prepared, output, frames, timeout=180):
    start = time.monotonic()
    model, prepared, output = Path(model), Path(prepared), Path(output)
    if output.exists():
        raise FileExistsError(output)
    if len(frames) < 2 or len(set(frames)) != len(frames):
        raise ValueError('Expected distinct training frame indices')
    manifest = json.loads((prepared/'manifest.json').read_text())
    records = {r['source_frame']: r for r in manifest['frames'] if r['lens'] == 'cam0' and r['split'] == 'train'}
    if any(n not in records for n in frames):
        raise ValueError('All requested cam0 frames must be original training captures')
    cameras = read_erp_cameras(model/'cameras.bin')
    if any(values[:2] != (2048, 1024) or not np.allclose(values[2:], [2048, 1024], rtol=0, atol=1e-9) for values in cameras.values()):
        raise ValueError('Expected native 2048x1024 ERP cameras')
    if any(records[n]['colmap_camera_id'] not in cameras for n in frames):
        raise ValueError('Requested view references an unknown camera')
    observations = modelio.observations(model/'images.bin')
    points = defaultdict(dict)
    source_hashes = {}
    masks = {}
    images = {}
    for frame in frames:
        row = records[frame]
        image_path = prepared/'images'/row['name']
        mask_path = prepared/'masks'/row['name']
        image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
        if image is None or mask is None or image.shape != (1024, 2048, 3) or mask.shape != (1024, 2048):
            raise ValueError('Expected native 2048 source and mask')
        images[frame], masks[frame] = image, mask
        source_hashes[row['name']] = {'image_sha256': sha(image_path), 'mask_sha256': sha(mask_path)}
        for xy, point_id in observations[row['source_name']].items():
            if frame in points[point_id]:
                raise ValueError('A point has multiple observations in one frame')
            points[point_id][frame] = xy
        if time.monotonic() - start > timeout:
            raise TimeoutError('Source inspection exceeded deadline')
    counts, common, conclusion = summarize_landmarks(points, frames)
    ranked = sorted(points, key=lambda point: (-len(points[point]), point))[:2]
    crop_size = 64
    tiles = []
    details = []
    for point in ranked:
        row_tiles = []
        per_view = []
        for frame in frames:
            tile = np.zeros((crop_size+22, crop_size, 3), np.uint8)
            pos = points[point].get(frame)
            item = {'frame': frame, 'observed': pos is not None}
            if pos is not None:
                x, y = map(lambda v: int(round(v)), pos)
                item['xy_native'] = list(pos)
                inside = 32 <= x < 2016 and 32 <= y < 992
                item['crop_inside'] = inside
                if inside:
                    crop = images[frame][y-32:y+32, x-32:x+32]
                    keep = masks[frame][y-32:y+32, x-32:x+32] == 255
                    item['valid_fraction'] = float(np.mean(keep))
                    if np.any(keep):
                        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
                        item['valid_gray_std_8bit'] = float(np.std(gray[keep]))
                    tile[22:] = crop
            cv2.putText(tile, str(frame), (1, 15), cv2.FONT_HERSHEY_SIMPLEX, .32, (255,255,255), 1, cv2.LINE_AA)
            row_tiles.append(tile)
            per_view.append(item)
        tiles.append(np.hstack(row_tiles))
        details.append({'point_id': point, 'view_count': len(points[point]), 'views': per_view})
    output.mkdir()
    sheet = None
    if tiles:
        sheet = output/'shared-landmark-source-crops.png'
        if not cv2.imwrite(str(sheet), np.vstack(tiles)):
            raise RuntimeError('Could not write source crops')
    report = {
        'method': f'Native-SfM landmark IDs in {len(frames)} original cam0 training images; 64x64 native source crops, no registration or resampling. Black tiles indicate absent observations. No holdout used.',
        'frames': frames,
        'shared_all_frames': len(common),
        'shared_by_view_count': {str(k): v for k, v in sorted(counts.items(), reverse=True)},
        'crops': details,
        'ranking': None,
        'conclusion': conclusion,
        'caveats': ['SfM landmark identity is estimated and not independent proof of correspondence.', 'Viewpoint, scale, lighting, and occlusion affect source appearance; grayscale standard deviation is contrast, not sharpness.', 'Source crops precede any scoring; no sharpness ranking is computed.'],
        'model_images_sha256': sha(model/'images.bin'),
        'model_cameras_sha256': sha(model/'cameras.bin'),
        'manifest_sha256': sha(prepared/'manifest.json'),
        'script_sha256': sha(Path(__file__)),
        'source_hashes': source_hashes,
        'crop_sheet_sha256': sha(sheet) if sheet else None,
        'elapsed_seconds': time.monotonic()-start,
    }
    encoded = json.dumps(report, indent=2, allow_nan=False)+'\n'
    if len(encoded.encode())+(sheet.stat().st_size if sheet else 0) > 3000000:
        raise ValueError('Report and crops exceed 3 MB')
    (output/'report.json').write_text(encoded)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('model', type=Path)
    parser.add_argument('prepared', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--frames', nargs='+', type=int, required=True)
    parser.add_argument('--timeout', type=int, default=180)
    args = parser.parse_args()
    report = audit(args.model, args.prepared, args.output, args.frames, args.timeout)
    print(json.dumps({'shared_all_frames': report['shared_all_frames'], 'ranking': report['ranking'], 'elapsed_seconds': report['elapsed_seconds']}))


if __name__ == '__main__':
    main()
