import json
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np
from review_candidates import create, verify


class ReviewCandidatesTest(unittest.TestCase):
    def test_sheets_keep_candidates_unreviewed_and_limit_frames(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            frames = root / 'frames'
            frames.mkdir()
            mask = root / 'mask.png'
            self.assertTrue(cv2.imwrite(str(mask), np.full((16, 32), 255, np.uint8)))
            self.assertTrue(cv2.imwrite(str(frames / 'frame_00000.png'), np.zeros((16, 32, 3), np.uint8)))
            manifest = root / 'manifest.json'
            manifest.write_text(json.dumps({'frames':[{'source_frame':5,'video_pts_s':.1,'mask':'mask.png'}]}))
            with self.assertRaises(ValueError):
                create(manifest, frames, root / 'too-many', 0)
            create(manifest, frames, root / 'review', 1)
            result = json.loads((root / 'review/manifest.json').read_text())
            self.assertIn('unreviewed', result['status'])
            self.assertEqual(result['source_frames'], [5])
            self.assertTrue((root / 'review/review-000.jpg').is_file())
            self.assertFalse((root / 'review/INCOMPLETE').exists())
            review = root / 'review/manifest.json'
            self.assertTrue(verify(review))
            image = frames / 'frame_00000.png'
            original_image = image.read_bytes()
            image.write_bytes(original_image + b'changed')
            with self.assertRaisesRegex(ValueError, 'frame changed'):
                verify(review)
            image.write_bytes(original_image)
            original_mask = mask.read_bytes()
            mask.write_bytes(original_mask + b'changed')
            with self.assertRaisesRegex(ValueError, 'mask changed'):
                verify(review)
            mask.write_bytes(original_mask)
            sheet = root / 'review/review-000.jpg'
            sheet.write_bytes(sheet.read_bytes() + b'changed')
            with self.assertRaisesRegex(ValueError, 'sheet changed'):
                verify(review)
            with self.assertRaises(FileExistsError):
                create(manifest, frames, root / 'review', 1)


if __name__ == '__main__':
    unittest.main()
