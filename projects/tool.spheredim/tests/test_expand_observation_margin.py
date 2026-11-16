import importlib.util
from pathlib import Path
import unittest
import numpy as np

spec = importlib.util.spec_from_file_location('margin', Path(__file__).resolve().parents[1] / 'scripts/expand_observation_margin.py')
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)

class AngularMarginTest(unittest.TestCase):
    def test_matches_spherical_distance_with_wrap_and_poles(self):
        h, w = 12, 24
        invalid = np.zeros((h, w), dtype=bool); invalid[3, 0] = True; invalid[7, 12] = True; invalid[0, 23] = True
        lat = np.pi / 2 - (np.arange(h) + 0.5) * np.pi / h
        lon = (np.arange(w) + 0.5) * 2 * np.pi / w
        for degrees in (0, 5, 20, 45):
            expected = np.zeros_like(invalid)
            for y, x in np.argwhere(invalid):
                dot = np.sin(lat)[:, None] * np.sin(lat[y]) + np.cos(lat)[:, None] * np.cos(lat[y]) * np.cos(lon[None, :] - lon[x])
                expected |= dot >= np.cos(np.deg2rad(degrees)) - 1e-12
            np.testing.assert_array_equal(module.angular_dilate(invalid, degrees), expected)

if __name__ == '__main__': unittest.main()
