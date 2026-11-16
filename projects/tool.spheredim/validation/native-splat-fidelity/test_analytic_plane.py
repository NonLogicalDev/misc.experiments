import unittest
import tempfile
from pathlib import Path

import cv2
import compare_analytic_plane as comparison
import numpy as np
import prepare_analytic_plane as plane


class AnalyticPlaneTest(unittest.TestCase):
    def test_center_camera_ray_plane_and_mask(self):
        rotation, center, translation = plane.camera(0, 0, 0)
        image, mask, rays, world_rays, distances = plane.render(rotation, center)
        y, x = plane.H // 2, plane.W // 2
        ray = rays[y, x]
        self.assertTrue(mask[y, x])
        np.testing.assert_allclose(translation, [0, 0, 0])
        np.testing.assert_allclose(ray, world_rays[y, x])
        point = center + distances[y, x] * world_rays[y, x]
        self.assertAlmostEqual(point[2], plane.PLANE_Z, places=12)
        np.testing.assert_array_equal(image[y, x], plane.chart(point[0], point[1]))
        self.assertFalse(mask[y, 0])  # the rear ray cannot hit the front plane
        self.assertTrue(np.all(image[~mask] == 0))

    def test_yaw_camera_pose_and_center(self):
        rotation, center, translation = plane.camera(.24, -.03, .12)
        np.testing.assert_allclose(rotation @ center + translation, 0, atol=1e-12)
        np.testing.assert_allclose(rotation @ rotation.T, np.eye(3), atol=1e-12)
        self.assertAlmostEqual(np.linalg.det(rotation), 1, places=12)


class ComparisonTest(unittest.TestCase):
    def test_score_uses_only_mask_and_excludes_boundary_for_ssim(self):
        source = np.zeros((30, 30, 3), dtype=np.uint8)
        render = np.full_like(source, 255)
        mask = np.zeros((30, 30), dtype=bool)
        mask[5:25, 5:25] = True
        render[mask] = 128
        result = comparison.score(source, render, mask)
        self.assertAlmostEqual(result['valid_mse'], (128 / 255) ** 2)
        self.assertEqual(result['ssim_interior_pixels'], 100)
        render[~mask] = 0
        self.assertAlmostEqual(comparison.score(source, render, mask)['valid_mse'], result['valid_mse'])

    def test_perfect_match_has_null_psnr_and_unit_ssim(self):
        source = np.full((20, 20, 3), 128, dtype=np.uint8)
        result = comparison.score(source, source.copy(), np.ones((20, 20), dtype=bool))
        self.assertEqual(result['valid_mse'], 0)
        self.assertIsNone(result['valid_psnr'])
        self.assertAlmostEqual(result['interior_ssim'], 1)

    def test_wrong_source_dimensions_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'images').mkdir()
            cv2.imwrite(str(root / 'images' / 'test.png'), np.zeros((20, 20, 3), dtype=np.uint8))
            with self.assertRaisesRegex(ValueError, 'Invalid source dimensions'):
                comparison.load_frame(root, 'test.png', 0)

    def test_missing_image_and_mismatched_phase_mask_are_clear_errors(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, 'Could not load image'):
                comparison.load_image(root / 'missing.png')
            for folder in ('images', 'masks', 'zero'):
                (root / folder).mkdir()
            image = np.zeros((plane.H, plane.W, 3), dtype=np.uint8)
            mask = np.full((plane.H, plane.W), 255, dtype=np.uint8)
            cv2.imwrite(str(root / 'images' / 'test.png'), image)
            cv2.imwrite(str(root / 'masks' / 'test.png'), mask)
            mask[0, 0] = 0
            cv2.imwrite(str(root / 'zero' / 'eval-mask-00000.png'), mask)
            with self.assertRaisesRegex(ValueError, 'zero mask differs'):
                comparison.load_frame(root, 'test.png', 0)

    def test_empty_and_too_small_masks_are_rejected(self):
        source = np.zeros((20, 20, 3), dtype=np.uint8)
        mask = np.zeros((20, 20), dtype=bool)
        mask[5:10, 5:10] = True
        with self.assertRaisesRegex(ValueError, 'no interior pixels'):
            comparison.score(source, source, mask)


if __name__ == '__main__':
    unittest.main()
