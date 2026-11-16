import unittest
import numpy as np
import audit_plane_reprojection as a
import compare_rigs as rig
class PlaneReprojectionTests(unittest.TestCase):
 def test_original_bearing_and_shifted_plane_point(self):
  xy=(700.,170.);ray=rig.ray(*xy,1024,512);pose=(np.eye(3),np.zeros(3));point=3*ray
  np.testing.assert_allclose(a.residual(point,pose,xy),[0,0],atol=1e-10)
  moved=point+np.array([.02,0.,0.]);self.assertGreater(np.linalg.norm(a.residual(moved,pose,xy)),.1)
if __name__=='__main__':unittest.main()
