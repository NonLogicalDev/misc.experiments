import importlib.util
from pathlib import Path
import unittest
import numpy as np

spec = importlib.util.spec_from_file_location('pose_diagnostic', Path(__file__).resolve().parents[1] / 'scripts' / 'diagnose_spherical_pose.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class BearingDiagnosticTests(unittest.TestCase):
    def test_native_erp_cardinal_rays_and_wrap(self):
        points = np.array([[512,256], [768,256], [0,256], [1024,256], [512,512]], dtype=float)
        actual = mod.image_rays(points, 1024, 512)
        np.testing.assert_allclose(actual, [[0,0,1], [1,0,0], [0,0,-1], [0,0,-1], [0,1,0]], atol=1e-12)
        with self.assertRaisesRegex(ValueError, '2:1'):
            mod.image_rays(points, 1023, 512)

    def test_heldout_fit_recovers_synthetic_rotation_with_outliers(self):
        rng = np.random.default_rng(7)
        source = rng.normal(size=(200, 3)); source /= np.linalg.norm(source, axis=1, keepdims=True)
        a = np.deg2rad(2.0)
        rotation = np.array([[np.cos(a), 0, np.sin(a)], [0,1,0], [-np.sin(a), 0, np.cos(a)]])
        dest = source @ rotation.T
        dest[:10] = rng.normal(size=(10,3)); dest[:10] /= np.linalg.norm(dest[:10], axis=1, keepdims=True)
        points = np.column_stack((rng.uniform(0,1024,200), rng.uniform(0,512,200)))
        result = mod.pose_quality(source, dest, points, 1024)
        self.assertAlmostEqual(result['fitted_rotation_degrees'], 2.0, places=4)
        self.assertLess(result['heldout_after_median_degrees'], 1e-4)
        self.assertGreater(result['heldout_before_median_degrees'], 1.0)

    def test_known_points_satisfy_spherical_epipolar_constraint(self):
        rng = np.random.default_rng(9)
        points = rng.uniform(-2, 2, size=(50,3)); points[:,2] += 5
        first = points / np.linalg.norm(points, axis=1, keepdims=True)
        baseline = np.array([0.4, 0, 0])
        second = points - baseline; second /= np.linalg.norm(second, axis=1, keepdims=True)
        result = mod.epipolar_quality(first, second, baseline)
        self.assertGreater(result['eligible_matches'], 40)
        self.assertLess(result['p90_degrees'], 1e-10)
        self.assertIsNone(mod.epipolar_quality(first, second, np.zeros(3)))

    def test_reject_underspecified_match_sets(self):
        rays = np.tile([0., 0., 1.], (15,1))
        with self.assertRaisesRegex(ValueError, '16 matches'):
            mod.pose_quality(rays, rays, np.zeros((15,2)), 1024)

if __name__ == '__main__': unittest.main()
