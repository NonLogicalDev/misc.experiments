import unittest
import numpy as np
import dis_depth_pilot as d
import temporal_depth_roi as erp

class DisDepthTests(unittest.TestCase):
 def test_rotated_cameras_recover_known_depth(self):
  angle=.1;R=np.array([[np.cos(angle),0,np.sin(angle)],[0,1,0],[-np.sin(angle),0,np.cos(angle)]]);p=np.array([.2,.1,4.]);a=(np.eye(3),np.zeros(3));b=(R,np.array([.4,0,0]))
  x0,y0,_=erp.project(p,*a,d.W,d.H);x1,y1,_=erp.project(p,*b,d.W,d.H);out,reason=d.triangulate(x0,y0,x1,y1,a,b)
  self.assertIsNone(reason);np.testing.assert_allclose(out,p,atol=1e-8)
 def test_dis_rotated_camera_recovers_known_sphere_depth(self):
  # The reference is at the sphere center, so the radial patch model is exact.
  yy,xx=np.indices((d.H,d.W));camera_rays=erp.rays(xx,yy,d.W,d.H)
  def render(center,rotation):
   rays=camera_rays@rotation;dot=np.sum(rays*center,axis=-1);t=-dot+np.sqrt(dot*dot+16-center@center);p=center+rays*t[...,None]
   values=128+40*np.sin(p[...,0]*45+p[...,1]*23)+35*np.cos(p[...,1]*37-p[...,0]*17)+25*np.sin(p[...,0]*27+p[...,1]*49)
   return np.clip(values,0,255).astype(np.uint8)
  a=(np.eye(3),np.zeros(3));angle=.07;R=np.array([[np.cos(angle),0,np.sin(angle)],[0,1,0],[-np.sin(angle),0,np.cos(angle)]]);b=(R,np.array([.6,0,0]));src=render(a[1],a[0]);dst=render(b[1],b[0])
  flow=d.dis_flow(src,dst,a[0],b[0]);u,v=flow[512,1024];point,reason=d.triangulate(1024,512,(1024+u)%d.W,512+v,a,b)
  self.assertIsNone(reason);self.assertLess(abs(np.linalg.norm(point)-4),.08)
  mask=np.full((d.H,d.W),255,np.uint8);self.assertTrue(d.unique_depth(src,dst,mask,mask,1024,512,point,a,b)[0])
 def test_periodic_seam_roll(self):
  self.assertAlmostEqual(float(d.wrapped_delta(1,2047)),2);self.assertAlmostEqual(float(d.wrapped_delta(2047,1)),-2)
  flow=np.zeros((4,8,2),np.float32);flow[:,7,0]=2;flow[:,0,0]=4;self.assertAlmostEqual(float(d.sample_flow(flow,7.5,1.5)[0]),3)
  m=np.full((d.H,d.W),255,np.uint8);self.assertTrue(d.full_mask(m,0,512,3));m[512,-1]=0;self.assertFalse(d.full_mask(m,0,512,3))
 def test_dis_wrapped_translation_matches_across_seam_roll(self):
  rng=np.random.default_rng(21);image=rng.integers(0,256,(d.H,d.W),dtype=np.uint8);target=np.roll(image,4,axis=1)
  f=d.dis_flow(image,target,np.eye(3),np.eye(3));g=d.dis_flow(np.roll(image,400,axis=1),np.roll(target,400,axis=1),np.eye(3),np.eye(3))
  for x in (1,2046):
   self.assertLess(abs(float(f[512,x,0])-4),.3)
   self.assertLess(abs(float(f[512,x,0])-float(g[512,(x+400)%d.W,0])),.3)
 def test_occluded_interpolation_footprint_rejected(self):
  flow=np.zeros((4,8,2),np.float32);flow[:,7,0]=2;flow[:,0,0]=4;self.assertAlmostEqual(float(d.sample_flow(flow,7.5,1.5)[0]),3)
  m=np.full((d.H,d.W),255,np.uint8);self.assertTrue(d.full_mask(m,600.2,400.5,3));m[402,602]=0;self.assertFalse(d.full_mask(m,600.2,400.5,3))
 def test_repetitive_stripes_not_evidence_of_unique_depth(self):
  x=np.arange(d.W);img=np.broadcast_to((128+100*np.sin(2*np.pi*x/8)).astype(np.uint8),(d.H,d.W)).copy();mask=np.full_like(img,255);pose0=(np.eye(3),np.zeros(3));pose1=(np.eye(3),np.array([.4,0,0]));p=np.array([0.,0.,4.]);good,_=d.unique_depth(img,img,mask,mask,1024,512,p,pose0,pose1);self.assertFalse(good)
if __name__=='__main__':unittest.main()
