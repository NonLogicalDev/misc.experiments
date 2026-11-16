import importlib.util,unittest
from pathlib import Path
import numpy as np
spec=importlib.util.spec_from_file_location('stereo',Path(__file__).resolve().parents[1]/'scripts'/'spherical_stereo.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class StereoTests(unittest.TestCase):
 def test_geometry_known_point(self):
  b=np.array([1.,0.,0.]);p=np.array([2.,3.,4.]);r0=p/np.linalg.norm(p);r1=(p-b)/np.linalg.norm(p-b);point,valid,gap=m.triangulate(r0,r1,b)
  self.assertTrue(valid);np.testing.assert_allclose(point,p,atol=1e-11);self.assertLess(gap,1e-11)
  B=m.basis_for_baseline(b);np.testing.assert_allclose(B.T@B,np.eye(3),atol=1e-12);np.testing.assert_allclose(B[:,2],b,atol=1e-12)
 def test_integer_correspondence_and_mask(self):
  rng=np.random.default_rng(5);a=rng.random((40,56),dtype=np.float32);b=np.zeros_like(a);b[3:]=a[:-3];mask=np.ones_like(a,dtype=bool);mask[15:22,20:27]=False
  shift,score,valid,margin,eligible,forward,reverse=m.stereo_ncc(a,b,mask,mask,5,5,minimum=.7,uniqueness=.05)
  self.assertGreater(valid.sum(),200);self.assertTrue(np.all(np.abs(shift[valid]-3)<.5));self.assertFalse(valid[18,23]);self.assertFalse(valid[1,2]);self.assertGreater(np.min(score[valid]),.7)
 def test_masked_source_pixels_cannot_change_valid_remap(self):
  h,w=16,32;mask=np.full((h,w),255,np.uint8);mask[5:9,0:3]=0
  im=np.full((h,w,3),100,np.uint8);changed=im.copy();changed[5:9,0:3]=255
  rays=m.rectified_rays(w,h,m.basis_for_baseline([1,0,0]));a,valid,_,_=m.remap(im,mask,rays);b,other,_,_=m.remap(changed,mask,rays)
  np.testing.assert_array_equal(valid,other);np.testing.assert_array_equal(a[valid],b[valid]);self.assertTrue(np.any(~valid))
 def test_subpixel_shift(self):
  import cv2
  rng=np.random.default_rng(23);a=cv2.GaussianBlur(rng.random((60,80),dtype=np.float32),(5,5),.8)
  b=np.zeros_like(a);b[4:]=a[:-4]*.6+a[1:-3]*.4
  mask=np.ones_like(a,dtype=bool);shift,score,ok,margin,eligible,forward,reverse=m.stereo_ncc(a,b,mask,mask,8,9,minimum=.7,uniqueness=.01)
  self.assertGreater(ok.sum(),100);self.assertLess(abs(float(np.median(shift[ok]))-3.6),.3)
 def test_mps_matches_cpu(self):
  import torch
  if not torch.backends.mps.is_available(): self.skipTest('MPS unavailable')
  rng=np.random.default_rng(7);a=rng.random((28,40),dtype=np.float32);b=np.zeros_like(a);b[4:]=a[:-4];valid=np.ones_like(a,dtype=bool)
  cpu=m.stereo_ncc(a,b,valid,valid,6,5,device='cpu');gpu=m.stereo_ncc(a,b,valid,valid,6,5,device='mps')
  np.testing.assert_array_equal(cpu[2],gpu[2]);np.testing.assert_allclose(cpu[0][cpu[2]],gpu[0][gpu[2]],atol=2e-5);np.testing.assert_allclose(cpu[1][cpu[2]],gpu[1][gpu[2]],atol=2e-5)
 def test_out_of_range_and_one_sided_ray(self):
  b=np.array([1.,0.,0.]);p=np.array([2.,3.,4.]);r0=p/np.linalg.norm(p);r1=(p-b)/np.linalg.norm(p-b);_,ok,_=m.triangulate(r0,-r1,b);self.assertFalse(ok)
if __name__=='__main__':unittest.main()
