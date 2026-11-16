import importlib.util
from pathlib import Path
import unittest
import numpy as np

spec = importlib.util.spec_from_file_location('spherical_eval', Path(__file__).resolve().parents[1] / 'scripts' / 'evaluate_spherical_renders.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class SphericalEvaluationTests(unittest.TestCase):
    def test_uniform_error_matches_known_psnr_and_invalid_area_ignored(self):
        ref = np.zeros((4,8,3), dtype=np.uint8)
        rendered = np.full_like(ref, 51)
        mask = np.full((4,8), 255, dtype=np.uint8)
        mask[0] = 0
        rendered[0] = 255
        result = mod.frame_metrics(ref, rendered, mask)
        self.assertAlmostEqual(result['pixel_psnr_db'], -20 * np.log10(0.2), places=6)
        self.assertAlmostEqual(result['spherical']['weighted_psnr_db'], -20 * np.log10(0.2), places=6)
        self.assertEqual(result['latitude_bands']['60..90'], None)
        self.assertAlmostEqual(result['valid_fraction'], 0.75)

    def test_spherical_area_downweights_polar_error(self):
        ref = np.zeros((6,12,3), dtype=np.uint8)
        mask = np.full((6,12), 255, dtype=np.uint8)
        polar = ref.copy(); polar[0] = 255
        equatorial = ref.copy(); equatorial[2] = 255
        pole = mod.frame_metrics(ref, polar, mask)
        equator = mod.frame_metrics(ref, equatorial, mask)
        self.assertAlmostEqual(pole['pixel_psnr_db'], equator['pixel_psnr_db'])
        self.assertGreater(pole['spherical']['weighted_psnr_db'], equator['spherical']['weighted_psnr_db'])

    def test_identical_image_gradients_and_empty_mask(self):
        ref = np.tile(np.arange(8, dtype=np.uint8), (4,1))[..., None].repeat(3, axis=2)
        mask = np.full((4,8), 255, dtype=np.uint8)
        result = mod.frame_metrics(ref, ref, mask)
        self.assertEqual(result['spherical']['weighted_mse'], 0)
        self.assertIsNone(result['spherical']['weighted_psnr_db'])
        self.assertAlmostEqual(result['spherical']['gradient_ratio'], 1.0)
        with self.assertRaisesRegex(ValueError, 'no valid pixels'):
            mod.frame_metrics(ref, ref, np.zeros_like(mask))

    def test_reject_non_spherical_dimensions(self):
        img = np.zeros((4,7,3), dtype=np.uint8)
        with self.assertRaisesRegex(ValueError, '2:1'):
            mod.frame_metrics(img, img, np.ones((4,7), dtype=np.uint8))

if __name__ == '__main__': unittest.main()
