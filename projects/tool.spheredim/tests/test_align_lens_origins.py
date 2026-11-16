import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import numpy as np
from scipy.spatial.transform import Rotation
import torch
import align_lens_origins as module


class LensOriginsTest(unittest.TestCase):
    def test_known_sphere_points_and_lens_rotation(self):
        directions = module.erp_directions(32, 16)
        baseline = np.array([1., .02, -.01])
        rotation = Rotation.from_euler('xyz', [.03, -.05, .02]).as_matrix()
        for radius in (2., 20., 200.):
            ray0, ray1 = module.source_rays(directions, baseline, radius, rotation)
            points = directions * radius
            distances0 = np.linalg.norm(points + baseline/2, axis=-1)
            distances1 = np.linalg.norm(points - baseline/2, axis=-1)
            np.testing.assert_allclose(-baseline/2 + ray0*distances0[..., None], points, atol=1e-12)
            np.testing.assert_allclose(baseline/2 + (ray1@rotation.T)*distances1[..., None], points, atol=1e-12)

    def test_infinite_depth_and_zero_baseline(self):
        directions = module.erp_directions(32, 16)
        for radius, baseline in ((np.inf, np.array([1., 0, 0])), (4., np.zeros(3))):
            ray0, ray1 = module.source_rays(directions, baseline, radius, np.eye(3))
            np.testing.assert_allclose(ray0, directions, atol=1e-14)
            np.testing.assert_allclose(ray1, directions, atol=1e-14)
        with self.assertRaises(ValueError):
            module.source_rays(directions, np.array([1., 0, 0]), .4, np.eye(3))

    def test_wrapped_interpolation_and_mask_support(self):
        image = np.full((8, 16, 3), 30, np.uint8)
        image[:, -1] = 90
        mask = np.full((8, 16), 255, np.uint8)
        ray = np.array([[[1., 0, 0]]])  # halfway between last and first column
        rgb, support, _ = module.sample_erp(image, mask, ray, 'cpu')
        self.assertTrue(support.item())
        np.testing.assert_array_equal(rgb, [[[60, 60, 60]]])
        mask[:, -1] = 0
        _, support, _ = module.sample_erp(image, mask, ray, 'cpu')
        self.assertFalse(support.item())

    @unittest.skipUnless(torch.backends.mps.is_available(), 'Apple GPU required')
    def test_gpu_cpu_sampling_agree(self):
        rng = np.random.default_rng(12)
        image = rng.integers(0, 255, (32, 64, 3), dtype=np.uint8)
        mask = np.full((32, 64), 255, np.uint8)
        mask[10:15, 20:25] = 0
        directions = module.erp_directions(60, 30)
        a = module.sample_erp(image, mask, directions, 'cpu')
        b = module.sample_erp(image, mask, directions, 'mps')
        np.testing.assert_allclose(a[0], b[0], atol=1)
        np.testing.assert_array_equal(a[1], b[1])


if __name__ == '__main__':
    unittest.main()
