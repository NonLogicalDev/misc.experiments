import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import numpy as np
from scipy.spatial.transform import Rotation
import fit_lens_rig as m
class RigTest(unittest.TestCase):
    def test_known_pose_depth_and_outliers(self):
        rng=np.random.default_rng(8);points=rng.normal(size=(500,3))*4;points[:,2]+=8
        t=np.array([1.,.03,-.02]);t/=np.linalg.norm(t)
        R=Rotation.from_rotvec([.04,.006,-.004]).as_matrix()
        target=points/np.linalg.norm(points,axis=1)[:,None]
        source=(points-t)@R;source/=np.linalg.norm(source,axis=1)[:,None]
        recovered,valid,gap=m.triangulate(source,target,R,t)
        self.assertTrue(valid.all());np.testing.assert_allclose(recovered,points,atol=1e-8)
        fitted,baseline,result=m.fit(source,target,np.eye(3))
        np.testing.assert_allclose(fitted,R,atol=1e-6);np.testing.assert_allclose(baseline,t,atol=1e-6)
        self.assertLess(np.max(abs(m.epipolar(source,target,fitted,baseline))),1e-7)
if __name__=='__main__':unittest.main()
