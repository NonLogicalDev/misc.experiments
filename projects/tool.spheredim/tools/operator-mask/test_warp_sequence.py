import unittest
import numpy as np
from warp_sequence import spherical_guard, warp

class MaskWarpTests(unittest.TestCase):
    def test_seam_and_pole_guard(self):
        mask=np.zeros((16,32),np.uint8)
        mask[8,0]=255
        mask[0,4]=255
        out=spherical_guard(mask,2)
        self.assertEqual(out[8,31],255)
        self.assertEqual(out[0,20],255)
        self.assertEqual(out[15,4],0)

    def test_identity_preserves_exclusions_without_inverting(self):
        mask=np.zeros((16,32),np.uint8)
        mask[2:5,7:10]=255
        mask[8,0]=255
        out=warp(mask,np.eye(3))
        self.assertTrue(np.all(out[mask != 0] == 255))
        self.assertEqual(out[12,16],0)

    def test_quarter_turn_maps_across_longitude(self):
        from scipy.spatial.transform import Rotation
        mask=np.zeros((16,32),np.uint8)
        mask[8,3]=255
        out=warp(mask,Rotation.from_euler('z',90,degrees=True).as_matrix())
        self.assertEqual(out[8,11],255)
        self.assertEqual(out[8,3],0)

    def test_odd_width_and_bad_guard_rejected(self):
        for mask,r in [(np.zeros((4,7),np.uint8),1),(np.zeros((4,8),np.uint8),4)]:
            with self.assertRaises(ValueError): spherical_guard(mask,r)

if __name__=='__main__': unittest.main()
