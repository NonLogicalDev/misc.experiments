import unittest
import json
import tempfile
from pathlib import Path
import cv2
import numpy as np
from propagate_candidates import remap, consistent, run


class PropagationGeometryTest(unittest.TestCase):
    def test_generates_with_only_keyframe_masks(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); frames = root / 'frames'; masks = root / 'masks'
            frames.mkdir(); masks.mkdir()
            for i in range(4):
                image = np.zeros((16, 32), np.uint8); image[5:10, 8:12] = 120
                cv2.imwrite(str(frames / f'frame_{i:05d}.png'), image)
                if i in (0, 3):
                    mask = np.full((16, 32), 255, np.uint8); mask[5:10, 8:12] = 0
                    cv2.imwrite(str(masks / f'frame_{i:05d}.png'), mask)
            source = root / 'source.json'
            source.write_text(json.dumps({'frames':[{'source_frame':5*i,'video_pts_s':i/6} for i in range(4)]}))
            result = run(frames, masks, source, root / 'output', 3, 1, 4)
            self.assertIn('UNREVIEWED', result['warning'])
            self.assertIsNone(result['frames'][1]['sam_excluded_candidate_kept_pixels'])
            self.assertEqual(len(list((root / 'output').glob('frame_*.png'))), 4)
            self.assertFalse((root / 'output/INCOMPLETE').exists())
            alternative = run(frames, masks, source, root / 'alternative', 3, 1, 4, 'nearest-consistent')
            self.assertEqual(alternative['fusion'], 'nearest-consistent')

    def test_longitude_wrap(self):
        image = np.zeros((4, 8), np.uint8); image[2, 0] = 255
        displacement = np.zeros((4, 8, 2), np.float32); displacement[2, 7, 0] = 1
        self.assertEqual(remap(image, displacement)[2, 7], 255)

    def test_pole_crossings_reflect_with_half_turn(self):
        image = np.zeros((4, 8), np.uint8); image[0, 4] = 255; image[3, 4] = 255
        displacement = np.zeros((4, 8, 2), np.float32); displacement[0, 0, 1] = -1; displacement[3, 0, 1] = 1
        result = remap(image, displacement)
        self.assertEqual(result[0, 0], 255); self.assertEqual(result[3, 0], 255)

    def test_inverse_motion_is_consistent_except_polar_crossings(self):
        a = np.zeros((4, 8, 2), np.float32); b = a.copy()
        a[:, :, 0] = 1; b[:, :, 0] = -1
        self.assertTrue(consistent(a, b)[1:3].all())
        b[:, :, 0] = 5
        self.assertFalse(consistent(a, b)[1:3].any())


if __name__ == '__main__': unittest.main()
