import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from audit_shared_source_patches import audit, summarize_landmarks


class SharedSourcePatchTests(unittest.TestCase):
    def test_landmark_summary_common_missing_and_empty(self):
        counts, common, conclusion = summarize_landmarks({4: {1: (0, 0), 2: (1, 1)}}, [1, 2])
        self.assertEqual(common, [4])
        self.assertEqual(counts[2], 1)
        self.assertIn('1 landmarks span', conclusion)
        _, common, conclusion = summarize_landmarks({4: {1: (0, 0)}}, [1, 2])
        self.assertEqual(common, [])
        self.assertIn('No landmark spans', conclusion)
        counts, common, conclusion = summarize_landmarks({}, [1, 2])
        self.assertEqual(dict(counts), {})
        self.assertEqual(common, [])
        self.assertIn('No tracked landmarks', conclusion)

    def test_rejects_wrong_camera_dimensions_before_reading_observations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepared = root/'prepared'
            prepared.mkdir()
            (prepared/'manifest.json').write_text(json.dumps({'frames': [
                {'source_frame': 1, 'lens': 'cam0', 'split': 'train', 'colmap_camera_id': 1},
                {'source_frame': 2, 'lens': 'cam0', 'split': 'train', 'colmap_camera_id': 1},
            ]}))
            with patch('audit_shared_source_patches.read_erp_cameras', return_value={1: (1024, 512, 1024, 512)}):
                with self.assertRaisesRegex(ValueError, '2048x1024'):
                    audit(root/'model', prepared, root/'out', [1, 2])
            self.assertFalse((root/'out').exists())

    def test_rejects_heldout_and_duplicate_frames_before_model_read(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepared = root/'prepared'
            prepared.mkdir()
            (prepared/'manifest.json').write_text(json.dumps({'frames': [
                {'source_frame': 1, 'lens': 'cam0', 'split': 'train'},
                {'source_frame': 2, 'lens': 'cam0', 'split': 'eval'},
            ]}))
            with self.assertRaises(ValueError):
                audit(root/'missing-model', prepared, root/'out', [1, 2])
            with self.assertRaises(ValueError):
                audit(root/'missing-model', prepared, root/'out', [1, 1])
            self.assertFalse((root/'out').exists())


if __name__ == '__main__':
    unittest.main()
