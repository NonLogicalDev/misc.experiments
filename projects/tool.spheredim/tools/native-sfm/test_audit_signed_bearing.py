import unittest
import tempfile
import struct
from pathlib import Path
import numpy as np
import audit_signed_bearing as a
import compare_rigs as rig

class SignedBearingTests(unittest.TestCase):
 def test_camera_rejects_non_erp_and_wrong_resolution(self):
  with tempfile.TemporaryDirectory() as temp:
   path=Path(temp)/'cameras.bin'
   path.write_bytes(struct.pack('<QiiQQdd',1,1,1,2048,1024,2048.,1024.))
   with self.assertRaisesRegex(ValueError,'model 17'):a.validate_native_cameras(path)
   path.write_bytes(struct.pack('<QiiQQdd',1,1,17,1024,512,1024.,512.))
   with self.assertRaisesRegex(ValueError,'2048x1024'):a.validate_native_cameras(path)
 def test_duplicate_training_source_rejected(self):
  row={'split':'train','source_name':'cam0/frame.png'}
  with self.assertRaisesRegex(ValueError,'Duplicate training source'):a.training_frames({'frames':[row,row]})
 def test_signed_tangent_residual_and_seam_wrap(self):
  points=np.array([rig.ray(1023,256,1024,512),rig.ray(2,257,1024,512)]);xy=np.array([[1,256],[1,256]])
  residual,_=a.signed_residual(points,np.eye(3),np.zeros(3),xy,1024,512)
  np.testing.assert_allclose(residual,[[-2,0],[1,1]],atol=1e-8)
 def test_coherence_distinguishes_cancelled_directions(self):
  self.assertAlmostEqual(a.summarize(np.array([[1.,0],[2,0]]))['directional_coherence'],1.)
  self.assertAlmostEqual(a.summarize(np.array([[1.,0],[-1,0]]))['directional_coherence'],0.)
if __name__=='__main__':unittest.main()
