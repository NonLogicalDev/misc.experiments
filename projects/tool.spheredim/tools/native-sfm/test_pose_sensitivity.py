import unittest
import struct
import tempfile
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
import pose_sensitivity as p
class RigPoseTests(unittest.TestCase):
 def test_rigid_body_perturbations_preserve_relative_camera_extrinsics(self):
  R=Rotation.from_euler('xyz',[.3,-.2,.6]).as_matrix();B=Rotation.from_euler('xyz',[-.02,.03,.01]).as_matrix();poses=[(R,np.array([2.,3.,4.])),(B@R,np.array([2.2,3.01,3.98]))]
  for axis in range(3):
   for angle in (-.1,.1):
    a,b=p.candidate_poses(poses,axis,angle,[.01,-.02,.03]);np.testing.assert_allclose(b[0]@a[0].T,poses[1][0]@poses[0][0].T,atol=1e-12);np.testing.assert_allclose(a[0]@(b[1]-a[1]),poses[0][0]@(poses[1][1]-poses[0][1]),atol=1e-12)
 def test_original_camera_dimensions_are_required(self):
  with tempfile.TemporaryDirectory() as tmp:
   camera=Path(tmp)/'cameras.bin';camera.write_bytes(struct.pack('<QiiQQdd',1,1,17,2048,1024,2048.,1024.))
   with self.assertRaisesRegex(ValueError,'1024x512'):p.validate_original_cameras(camera)
   camera.write_bytes(struct.pack('<QiiQQdd',1,1,17,1024,512,1024.,512.));self.assertEqual(len(p.validate_original_cameras(camera)),1)
 def test_identity_preserves_exact_pose(self):
  x=[(np.eye(3),np.array([1.,2.,3.])),(np.eye(3),np.array([1.2,2.,3.]))];y=p.candidate_poses(x,0,0,[0,0,0]);
  for a,b in zip(x,y):np.testing.assert_allclose(a[0],b[0]);np.testing.assert_allclose(a[1],b[1])
if __name__=='__main__':unittest.main()
