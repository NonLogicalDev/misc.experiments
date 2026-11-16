import importlib.util
from pathlib import Path
import unittest
import numpy as np

spec = importlib.util.spec_from_file_location('observed', Path(__file__).resolve().parents[1] / 'scripts/export_observed_sample.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class ValidationTest(unittest.TestCase):
    def test_valid_frame_and_invalid_samples(self):
        color = np.array([[[1, 2, 3], [0, 0, 0]]], dtype=np.uint8)
        mask = np.array([[[255, 255, 255], [0, 0, 0]]], dtype=np.uint8)
        owner = np.array([[[255, 0, 0], [0, 0, 0]]], dtype=np.uint8)
        module.validate_frame(color, mask, owner)
        broken = color.copy(); broken[0, 1, 0] = 1
        with self.assertRaises(ValueError): module.validate_frame(broken, mask, owner)
        broken = mask.copy(); broken[0, 1, 0] = 128
        with self.assertRaises(ValueError): module.validate_frame(color, broken, owner)
        broken = owner.copy(); broken[0, 0] = [1, 1, 1]
        with self.assertRaises(ValueError): module.validate_frame(color, mask, broken)
        with self.assertRaises(ValueError): module.validate_frame(color, mask[:, :1], owner)

if __name__ == '__main__': unittest.main()
