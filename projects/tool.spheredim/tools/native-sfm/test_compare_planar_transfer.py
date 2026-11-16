import unittest
import numpy as np
import compare_planar_transfer as p
class PlanarTransferTests(unittest.TestCase):
 def test_identity_and_translated_camera_analytic_plane(self):
  I=np.eye(3);zero=np.zeros(3);target=(I,zero);normal=np.array([0.,0.,1.]);x=np.array([1024.,1050.]);y=np.array([512.,500.])
  sx,sy,ok=p.inverse_plane_map(x,y,target,target,normal,-4.);np.testing.assert_allclose(sx,x,atol=1e-10);np.testing.assert_allclose(sy,y,atol=1e-10);self.assertTrue(ok.all())
  sx,sy,ok=p.inverse_plane_map(np.array([1024.]),np.array([512.]),target,(I,np.array([.4,0,0])),normal,-4.);self.assertTrue(ok[0]);ray=p.erp.rays(1024.5,512.5,2048,1024);world=ray*(4/ray[2]);v=world-np.array([.4,0,0]);self.assertAlmostEqual(sx[0],(np.arctan2(v[0],v[2])/(2*np.pi)+.5)*2048-.5);self.assertAlmostEqual(sy[0],(np.arctan2(v[1],np.hypot(v[0],v[2]))/np.pi+.5)*1024-.5)
  _,_,ok=p.inverse_plane_map(np.array([1024.]),np.array([512.]),target,target,normal,4.);self.assertFalse(ok[0])
 def test_nonidentity_transfer_samples_analytic_pixel_center_image(self):
  I=np.eye(3);center=np.array([.2,0.,0.]);target=(I,np.zeros(3));source=(I,center)
  tx=np.array([1000.,1024.,1040.]);ty=np.array([500.,512.,520.]);sx,sy,valid=p.inverse_plane_map(tx,ty,target,source,np.array([0.,0.,1.]),-4.)
  # This continuous raster is affine in pixel-center coordinates, so bilinear
  # interpolation must reproduce its analytic value at the projected center.
  yy,xx=np.indices((p.H,p.W));image=np.stack((xx.astype(float),yy.astype(float),(xx+yy).astype(float)),axis=-1);mask=np.full((p.H,p.W),255,np.uint8)
  value,supported=p.bilinear_rgb(image,mask,sx,sy);self.assertTrue((valid & supported).all())
  expected=np.column_stack((sx,sy,sx+sy))
  np.testing.assert_allclose(value,expected,atol=1e-9)
 def test_hull_excludes_outside_and_partial_boundary_sampling(self):
  hull=p.hull_support((8,8),[[2,2],[5,2],[5,5],[2,5]]);image=np.ones((8,8,3),np.uint8)*99
  _,valid=p.bilinear_rgb(image,hull,np.array([3.5,5.5,1.5]),np.array([3.5,3.5,3.5]));np.testing.assert_array_equal(valid,[True,False,False])
 def test_all_four_mask_neighbors_required_and_seam_wraps(self):
  im=np.arange(4*8*3,dtype=np.uint8).reshape(4,8,3);m=np.full((4,8),255,np.uint8);_,ok=p.bilinear_rgb(im,m,np.array([7.5]),np.array([1.5]));self.assertTrue(ok[0]);m[2,0]=0;_,ok=p.bilinear_rgb(im,m,np.array([7.5]),np.array([1.5]));self.assertFalse(ok[0])
if __name__=='__main__':unittest.main()
