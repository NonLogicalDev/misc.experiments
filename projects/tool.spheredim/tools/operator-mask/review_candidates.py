#!/usr/bin/env python3
"""Create contact sheets for candidate masks; this does not approve masks."""
import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def create(manifest_path, frames_dir, output, max_frames):
    manifest = json.loads(manifest_path.read_text())
    records = manifest['frames']
    if not records or len(records) > max_frames:
        raise ValueError('Frame count is empty or exceeds --max-frames')
    indices = [r['source_frame'] for r in records]
    if len(set(indices)) != len(indices) or indices != sorted(indices):
        raise ValueError('Source frame indices must be unique and ordered')
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    (output / 'INCOMPLETE').write_text('Review sheets are incomplete.\n')
    cells = []
    inputs = []
    for ordinal, record in enumerate(records):
        frame = frames_dir / f'frame_{ordinal:05d}.png'
        mask = manifest_path.parent / record['mask']
        frame_bytes, mask_bytes = frame.read_bytes(), mask.read_bytes()
        image = cv2.imdecode(np.frombuffer(frame_bytes, np.uint8), cv2.IMREAD_COLOR)
        keep = cv2.imdecode(np.frombuffer(mask_bytes, np.uint8), cv2.IMREAD_GRAYSCALE)
        inputs.append({'source_frame': record['source_frame'], 'frame': str(frame.resolve()),
                       'frame_sha256': hashlib.sha256(frame_bytes).hexdigest(),
                       'mask': str(mask.resolve()), 'mask_sha256': hashlib.sha256(mask_bytes).hexdigest()})
        if image is None or keep is None or image.shape[:2] != keep.shape:
            raise ValueError(f'Frame or mask invalid for source frame {record["source_frame"]}')
        overlay = image.copy()
        overlay[keep < 128] = (overlay[keep < 128] * .35 + np.array([0, 0, 165])).clip(0, 255)
        thumbnail = cv2.resize(overlay, (512, 256), interpolation=cv2.INTER_AREA)
        cv2.rectangle(thumbnail, (0, 0), (512, 24), (0, 0, 0), -1)
        label = f'UNREVIEWED frame {record["source_frame"]} {record["video_pts_s"]:.3f}s'
        cv2.putText(thumbnail, label, (5, 17), cv2.FONT_HERSHEY_SIMPLEX, .45, (255, 255, 255), 1, cv2.LINE_AA)
        cells.append(thumbnail)
    names = []
    for page in range((len(cells) + 7) // 8):
        group = cells[page * 8:page * 8 + 8]
        group += [np.zeros_like(cells[0])] * (8 - len(group))
        sheet = np.vstack([np.hstack(group[i:i + 2]) for i in range(0, 8, 2)])
        name = f'review-{page:03d}.jpg'
        if not cv2.imwrite(str(output / name), sheet):
            raise OSError(f'Cannot write {name}')
        names.append(name)
    result = {'status': 'unreviewed candidates; sheets do not approve masks',
              'mask_manifest': str(manifest_path.resolve()), 'mask_manifest_sha256': digest(manifest_path),
              'frames_directory': str(frames_dir.resolve()), 'frame_count': len(records),
              'sheet_names': names, 'sheet_sha256': {name: digest(output / name) for name in names},
              'source_frames': indices, 'inputs': inputs}
    (output / 'manifest.json').write_text(json.dumps(result, indent=2) + '\n')
    (output / 'INCOMPLETE').unlink()


def verify(review_manifest):
    """Verify reviewed files are unchanged; this does not attest human review."""
    review_manifest = Path(review_manifest)
    result = json.loads(review_manifest.read_text())
    source = Path(result['mask_manifest'])
    if digest(source) != result['mask_manifest_sha256']:
        raise ValueError('Candidate manifest changed')
    records = json.loads(source.read_text())['frames']
    inputs = result['inputs']
    if len(records) != result['frame_count'] or len(inputs) != len(records):
        raise ValueError('Review record count mismatch')
    indices = [r['source_frame'] for r in records]
    if indices != result['source_frames'] or indices != [r['source_frame'] for r in inputs]:
        raise ValueError('Review frame order mismatch')
    for ordinal, (record, item) in enumerate(zip(records, inputs)):
        expected_frame = Path(result['frames_directory']) / f'frame_{ordinal:05d}.png'
        expected_mask = source.parent / record['mask']
        for label, path, expected_path in (('frame', Path(item['frame']), expected_frame), ('mask', Path(item['mask']), expected_mask)):
            if path.resolve() != expected_path.resolve() or digest(path) != item[label + '_sha256']:
                raise ValueError(f'{label} changed for source frame {record["source_frame"]}')
    sheets = result['sheet_names']
    if len(sheets) != (len(records) + 7) // 8 or set(sheets) != set(result['sheet_sha256']):
        raise ValueError('Review sheets missing or inconsistent')
    for name in sheets:
        if Path(name).name != name or digest(review_manifest.parent / name) != result['sheet_sha256'][name]:
            raise ValueError(f'Review sheet changed: {name}')
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mask_manifest', type=Path)
    parser.add_argument('stabilized_frames', type=Path, help='ordinal frame_00000.png etc. in manifest order')
    parser.add_argument('output', type=Path, help='new directory')
    parser.add_argument('--max-frames', type=int, required=True)
    args = parser.parse_args()
    create(args.mask_manifest, args.stabilized_frames, args.output, args.max_frames)


if __name__ == '__main__':
    main()
