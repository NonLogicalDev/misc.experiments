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


if __name__=='__main__':unittest.main()
