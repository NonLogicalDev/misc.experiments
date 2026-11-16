import unittest
import numpy as np
import targeted_geometry_tracks as t
import compare_rigs as rig


class GeometryTests(unittest.TestCase):
    def test_pixel_round_trip_and_signed_residual(self):
        for xy in ([100,200],[512,256],[1000,400]):
            np.testing.assert_allclose(t.predicted_xy(rig.ray(*xy,1024,512)),xy,atol=1e-9)
        measured=[512,256];point=rig.ray(514,255,1024,512)*10
        result=t.target_residual(point,(np.eye(3),np.zeros(3)),measured)
        self.assertAlmostEqual(result['horizontal_px'],2);self.assertAlmostEqual(result['vertical_px'],-1)

    def test_degenerate_neighbors_are_not_scored(self):
        poses={'a':(np.eye(3),np.zeros(3)),'b':(np.eye(3),np.zeros(3)),'c':(np.eye(3),np.zeros(3))}
        result,reason=t.calculate_track(('a',(512,256)),[('b',(512,256)),('c',(512,256))],poses)
        self.assertIsNone(result);self.assertEqual(reason,'degenerate')


if __name__=='__main__':unittest.main()
