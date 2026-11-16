import unittest
import numpy as np
import compare_splat_resolutions as c

class ResolutionComparisonTests(unittest.TestCase):
 def setUp(self):
  self.lo=np.full((512,1024,3),32,np.uint8);self.hi=np.full((1024,2048,3),32,np.uint8);self.lm=np.full((512,1024),255,np.uint8);self.hm=np.full((1024,2048),255,np.uint8)
 def test_camera_model_and_scaled_intrinsics(self):
  low='1 EQUIRECTANGULAR 1024 512 1024 512\n2 EQUIRECTANGULAR 1024 512 1024 512\n';high='1 EQUIRECTANGULAR 2048 1024 2048 1024\n2 EQUIRECTANGULAR 2048 1024 2048 1024\n';c.validate_cameras(low,high)
  with self.assertRaisesRegex(ValueError,'camera model'):c.validate_cameras(low,high.replace('EQUIRECTANGULAR','PINHOLE',1))
  with self.assertRaisesRegex(ValueError,'intrinsics differ'):c.validate_cameras(low,high.replace('2048 1024 2048 1024','2048 1024 2047 1024',1))
 def test_exact_reference_and_support(self):
  self.assertEqual(c.reduce_candidate(self.hi,self.hm,self.lo,self.lm,self.hi).shape,self.lo.shape)
 def test_changed_source_and_support_rejected(self):
  self.hi[0,0]=48
  with self.assertRaisesRegex(ValueError,'source differs'):c.reduce_candidate(self.hi,self.hm,self.lo,self.lm,self.hi)
  self.hi[0,0]=32;self.hm[0,0]=0
  with self.assertRaisesRegex(ValueError,'support differs'):c.reduce_candidate(self.hi,self.hm,self.lo,self.lm,self.hi)
if __name__=='__main__':unittest.main()
