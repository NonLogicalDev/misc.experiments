import unittest
import tempfile
import struct
from pathlib import Path
import numpy as np
import audit_seed_gauge as a
import compare_rigs as rig

class SeedGaugeTests(unittest.TestCase):
    def test_similarity_recovers_nonidentity_rotation_scale_and_translation(self):
        src=np.array([[0,0,0],[2,0,0],[0,1,0],[0,0,3],[1,2,3]],float);theta=.4
        R=np.array([[np.cos(theta),0,np.sin(theta)],[0,1,0],[-np.sin(theta),0,np.cos(theta)]])
        target=2.3*(src@R.T)+[1,-2,3];s,r,t=a.fit_similarity(src,target)
        np.testing.assert_allclose(s,2.3,atol=1e-10);np.testing.assert_allclose(r,R,atol=1e-10);np.testing.assert_allclose(t,[1,-2,3],atol=1e-10)
    def test_camera_models_must_be_scaled_native_erp(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'cameras.bin'
            path.write_bytes(struct.pack('<QiiQQdd',1,1,17,1024,512,1024.,512.))
            low=a.read_erp_cameras(path)
            a.validate_2x_cameras(low,{1:(2048,1024,2048.,1024.)})
            with self.assertRaisesRegex(ValueError,'matching'):a.validate_2x_cameras(low,{1:(2048,1024,2047.,1024.)})
            path.write_bytes(struct.pack('<QiiQQdd',1,1,1,1024,512,1024.,512.))
            with self.assertRaisesRegex(ValueError,'model 17'):a.read_erp_cameras(path)

    def test_collinear_centers_rejected(self):
        with self.assertRaisesRegex(ValueError,'Degenerate'):a.fit_similarity([[0,0,0],[1,0,0],[2,0,0]],[[0,0,0],[1,0,0],[2,0,0]])
    def test_off_axis_bearing_under_rotated_camera(self):
        R=rig.rotation([.9,.1,.2,-.3]);C=np.array([1,2,-1]);xy=np.array([[710.,160.]]);point=C+5*(R.T@rig.ray(*xy[0],1024,512))
        self.assertLess(a.angular_errors(point[None],R,C,xy,1024)[0],1e-5)
        self.assertGreater(a.angular_errors((-point+2*C)[None],R,C,xy,1024)[0],500)
    def test_track_rejects_repeated_timestamp_wrong_direction_and_weak_parallax(self):
        self.assertFalse(a.point_gate([.1,.1,.1],[1,1,2],5));self.assertFalse(a.point_gate([.1,.1,3],[1,2,3],5));self.assertFalse(a.point_gate([.1,.1,.1],[1,2,3],.2));self.assertTrue(a.point_gate([.1,.2,.3],[1,2,3],2))
    def test_parallax_uses_observed_camera_centers(self):
        p=np.array([0.,0.,10.]);self.assertAlmostEqual(a.parallax(p,[[0,0,0],[1,0,0]]),np.degrees(np.arctan(.1)))
if __name__=='__main__':unittest.main()
