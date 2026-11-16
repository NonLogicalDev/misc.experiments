import unittest
import numpy as np
from scipy.spatial.transform import Rotation
import audit_motion as a

class MotionTests(unittest.TestCase):
 def fixture(self):
  frames=[{'source_frame':n,'timestamp_microseconds':i*500000} for i,n in enumerate((10,30,50))];poses={};priors={};world=Rotation.from_euler('z',40,degrees=True).as_matrix();rig=Rotation.from_euler('y',3,degrees=True).as_matrix()
  for i,f in enumerate(frames):
   body=Rotation.from_euler('x',i*10,degrees=True).as_matrix();q=world@body
   for j in (0,1):
    name=f'cam{j}/frame_{f["source_frame"]:06}.png';local=np.eye(3) if j==0 else rig;poses[name]=((body@local).T,np.array([i*.1,j*.03,0.]));priors[name]=q@local
  return frames,poses,priors
 def test_aligned_motion_and_rig(self):
  frames,poses,priors=self.fixture();r=a.audit(frames,poses,priors,5,2)
  self.assertEqual(r['coverage']['frames_both_lenses'],3);self.assertLess(r['world_alignment']['residual_degrees']['max'],1e-5);self.assertLess(r['adjacent_rotation_disagreement_degrees']['max'],1e-5);self.assertAlmostEqual(r['speed']['median'],.2)
 def test_error_missing_and_validation(self):
  frames,poses,priors=self.fixture();poses['cam0/frame_000030.png']=(Rotation.from_euler('x',30,degrees=True).as_matrix(),np.zeros(3));r=a.audit(frames,poses,priors,5,.01);self.assertTrue(r['intervals'][0]['rotation_flag']);self.assertTrue(r['intervals'][1]['speed_flag'])
  del poses['cam0/frame_000030.png'];r=a.audit(frames,poses,priors,5,2);self.assertEqual(len(r['coverage']['missing_images']),1);self.assertIn('missing_images',r['intervals'][0])
  with self.assertRaises(ValueError):a.audit(frames+[frames[-1]],poses,priors,5,2)
  priors.pop(next(iter(priors)))
  with self.assertRaises(ValueError):a.audit(frames,poses,priors,5,2)
if __name__=='__main__':unittest.main()
