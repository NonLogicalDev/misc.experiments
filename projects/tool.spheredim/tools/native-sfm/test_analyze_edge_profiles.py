import unittest
import cv2
import numpy as np
import analyze_edge_profiles as a


class EdgeProfileTests(unittest.TestCase):
    def test_blur_shift_and_contrast_controls(self):
        src=np.zeros((96,128),np.uint8)+30;src[:,64:]=210;mask=np.full_like(src,255);region=[20,20,88,56]
        identity=a.profiles(src,src,mask,region)
        blur=a.profiles(src,cv2.GaussianBlur(src,(0,0),2),mask,region)
        shifted=a.profiles(src,cv2.warpAffine(src,np.float32([[1,0,2],[0,1,0]]),(128,96),borderMode=cv2.BORDER_REPLICATE),mask,region)
        contrast=a.profiles(src,(30+(src.astype(np.float32)-30)*.5).astype(np.uint8),mask,region)
        self.assertAlmostEqual(identity['contrast_ratio']['median'],1,places=3)
        self.assertGreater(blur['render_width_10_90_px']['median'],identity['render_width_10_90_px']['median']+2)
        self.assertAlmostEqual(shifted['signed_centroid_shift_px']['median'],2,delta=.2)
        self.assertAlmostEqual(contrast['contrast_ratio']['median'],.5,delta=.03)
        self.assertAlmostEqual(contrast['signed_centroid_shift_px']['median'],0,delta=.1)

    def test_gradient_diagnostic_detects_blur_shift_and_contrast(self):
        src=np.zeros((96,128),np.uint8)+30;src[:,64:]=210;mask=np.full_like(src,255);region=[20,20,88,56]
        blurred=cv2.GaussianBlur(src,(0,0),2)
        shifted=cv2.warpAffine(src,np.float32([[1,0,2],[0,1,0]]),(128,96),borderMode=cv2.BORDER_REPLICATE)
        contrast=(30+(src.astype(np.float32)-30)*.5).astype(np.uint8)
        self.assertLess(a.gradient_diagnostic(src,blurred,mask,region)['render_to_source_gradient_rms'],.8)
        self.assertEqual(a.gradient_diagnostic(src,shifted,mask,region)['best_integer_shift_px'][0],2)
        self.assertAlmostEqual(a.gradient_diagnostic(src,contrast,mask,region)['render_to_source_gradient_rms'],.5,delta=.03)

    def test_fully_invalid_mask_rejected(self):
        src=np.zeros((64,64),np.uint8);src[:,32:]=255
        with self.assertRaisesRegex(ValueError,'No valid source edges'):
            a.profiles(src,src,np.zeros_like(src),[0,0,64,64])

class FrequencyDiagnosticTests(unittest.TestCase):
    def test_texture_fidelity_controls(self):
        rng = np.random.default_rng(45)
        src = np.clip(128 + rng.normal(0, 30, (128, 128)), 0, 255).astype(np.uint8)
        wrong = np.clip(128 + rng.normal(0, 30, (128, 128)), 0, 255).astype(np.uint8)
        mask = np.full_like(src, 255)
        region = [0, 0, 128, 128]
        blurred = cv2.GaussianBlur(src, (0, 0), 2)
        shifted = np.roll(src, 2, axis=1)
        def band(image):
            return a.frequency_diagnostic(src, image, mask, region)['bands_cycles_per_pixel']['1/8-1/4']
        same, blur, shift, other = map(band, (src, blurred, shifted, wrong))
        self.assertAlmostEqual(same['coherence'], 1)
        self.assertAlmostEqual(same['gain'], 1)
        self.assertAlmostEqual(same['residual_to_source_energy'], 0)
        self.assertLess(blur['gain'], .5)
        self.assertLess(shift['coherence'], .5)
        self.assertAlmostEqual(other['render_to_source_energy'], 1, delta=.15)
        self.assertLess(abs(other['coherence']), .15)
        self.assertGreater(other['residual_to_source_energy'], 1.5)

    def test_constant_render_reports_missing_detail(self):
        rng = np.random.default_rng(47)
        src = np.clip(128 + rng.normal(0, 30, (128, 128)), 0, 255).astype(np.uint8)
        render = np.full_like(src, 128)
        bands = a.frequency_diagnostic(src, render, np.full_like(src, 255), [0, 0, 128, 128])['bands_cycles_per_pixel']
        for band in bands.values():
            self.assertEqual(band['status'], 'ok')
            self.assertAlmostEqual(band['render_to_source_energy'], 0)
            self.assertIsNone(band['coherence'])
            self.assertAlmostEqual(band['gain'], 0)
            self.assertAlmostEqual(band['residual_to_source_energy'], 1)

    def test_invalid_inputs_and_scaled_regions(self):
        image = np.full((128, 256), 128, np.uint8)
        mask = np.full_like(image, 255)
        self.assertEqual(a.scaled_rect([384, 256, 256, 256], image.shape), [96, 64, 64, 64])
        with self.assertRaisesRegex(ValueError, 'Constant'):
            a.frequency_diagnostic(image, image, mask, [0, 0, 64, 64])
        with self.assertRaisesRegex(ValueError, 'too small'):
            a.scaled_rect([0, 0, 256, 256], (32, 64))
        with self.assertRaisesRegex(ValueError, 'Too few'):
            a.frequency_diagnostic(image, image, np.zeros_like(mask), [0, 0, 64, 64])


if __name__=='__main__':unittest.main()
