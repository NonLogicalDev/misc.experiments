import unittest
import numpy as np
import audit_landmark_coverage as a


class CoverageTests(unittest.TestCase):
    def test_stereo_does_not_count_as_temporal_baseline(self):
        observations=[(1,'cam0',np.array([0.,0.,0.])),(1,'cam1',np.array([.1,0.,0.])),(2,'cam0',np.array([1.,0.,0.]))]
        stereo=a.measure(np.array([0.,0.,4.]),observations,{1})
        self.assertEqual(stereo['observations'],2);self.assertEqual(stereo['timestamps'],1);self.assertEqual(stereo['stereo_timestamps'],1);self.assertIsNone(stereo['max_baseline'])
        both=a.measure(np.array([0.,0.,4.]),observations,{1,2})
        self.assertEqual(both['timestamps'],2);self.assertAlmostEqual(both['max_baseline'],1);self.assertGreater(both['max_view_angle_degrees'],0)

    def test_absent_track_is_counted_as_zero(self):
        row=a.measure(np.array([0.,0.,4.]),[(1,'cam0',np.zeros(3))],{2})
        self.assertEqual(row['timestamps'],0);self.assertEqual(a.summary([row])['timestamp_count_histogram_5_plus'],{'0':1})


if __name__=='__main__':unittest.main()
