import unittest
import numpy as np
import poster_plane_sweep as p
import temporal_depth_roi as erp

class PosterPlaneTests(unittest.TestCase):
 def test_parallel_plane_intersection_and_nonpositive_rejected(self):
  rays=np.array([[0.,0.,1.],[0.,0.,-1.]]);world,valid=p.intersect(rays,np.zeros(3),np.array([0.,0.,1.]),[-4.])
  np.testing.assert_allclose(world[0,0],[0,0,4]);np.testing.assert_array_equal(valid,[[True,False]])
 def test_textured_plane_across_three_cameras(self):
  yy,xx=np.indices((p.H,p.W));rays=erp.rays(xx,yy,p.W,p.H);normal=np.array([0.,0.,1.])
  def render(center):
   distance=(4-center[2])/rays[...,2];world=center+rays*distance[...,None]
   val=128+35*np.sin(world[...,0]*34+world[...,1]*17)+30*np.cos(world[...,1]*37-world[...,0]*21)+20*np.sin(world[...,0]*19+world[...,1]*41)
   return np.clip(val,0,255).astype(np.uint8)
  zero=np.zeros(3);mask=np.full((p.H,p.W),255,np.uint8);ref=render(zero);centers=[np.array([-.5,0,0]),np.array([.5,0,0]),np.array([0,.5,0])];targets=[(render(c),mask,(np.eye(3),c)) for c in centers];offsets=np.linspace(-4.6,-3.4,33)
  result,reason=p.patch_scores(ref,mask,(np.eye(3),zero),targets,1024,512,offsets,normal);self.assertIsNone(reason);scores,coords=result;k,reason=p.select(scores,coords);self.assertIsNone(reason);self.assertLess(abs(offsets[k]+4),.08)
  mask[512,1024]=0;self.assertEqual(p.patch_scores(ref,mask,(np.eye(3),zero),targets,1024,512,offsets,normal)[1],'reference_mask')
 def test_repeated_stripe_images_do_not_produce_unique_depth(self):
  xx=np.arange(p.W);stripe=np.broadcast_to((128+100*np.sin(2*np.pi*xx/8)).astype(np.uint8),(p.H,p.W)).copy();mask=np.full((p.H,p.W),255,np.uint8);C=np.zeros(3);centers=[np.array([-.5,0,0]),np.array([.5,0,0]),np.array([0,.5,0])];targets=[(stripe,mask,(np.eye(3),c)) for c in centers]
  data,reason=p.patch_scores(stripe,mask,(np.eye(3),C),targets,1024,512,np.linspace(-4.6,-3.4,33),np.array([0.,0.,1.]));self.assertIsNone(reason);self.assertIsNone(p.select(*data)[0])
 def test_fixed_plane_competitor_margins_are_measured_at_requested_depth(self):
  scores=np.array([[.7,.9,.95,.6]]);coords=np.array([[[0.,0.],[2.,0.],[4.,0.],[6.,0.]]]);self.assertAlmostEqual(p.competitor_margins(scores,coords,1)[0],-.05)
  coords[:]=0;self.assertIsNone(p.competitor_margins(scores,coords,1)[0])
 def test_competing_repeated_texture_rejected(self):
  scores=np.zeros((3,33));scores[:,10]=.95;scores[:,22]=.94;coords=np.broadcast_to(np.column_stack((np.arange(33),np.zeros(33))),(3,33,2));self.assertEqual(p.select(scores,coords)[1],'ambiguous_depth')
  close=np.zeros((3,33,2));self.assertEqual(p.select(scores,close)[1],'depth_unresolved')
if __name__=='__main__':unittest.main()
