import unittest
import numpy as np
from register_rig_frames import match_distinct_landmarks, uncertainty


class LandmarkRatioTest(unittest.TestCase):
    def test_duplicate_source_descriptors_are_one_landmark(self):
        query=np.array([[0.,0.]])
        descriptors=np.array([[1.,0.],[1.1,0.],[8.,0.]])
        matches=match_distinct_landmarks(query,descriptors,[12,12,33],ratio=.8)
        self.assertEqual(matches[0][:2],(0,0))

    def test_rejects_ambiguous_different_landmarks(self):
        self.assertEqual(match_distinct_landmarks([[0.,0.]], [[1.,0.],[-1.,0.]], [12,33]), [])

    def test_rejects_when_only_one_landmark_exists(self):
        self.assertEqual(match_distinct_landmarks([[0.,0.]], [[1.,0.],[2.,0.]], [12,12]), [])

    def test_uncertainty_rejects_degenerate_geometry(self):
        points=np.tile([0.,0.,1.],(10,1)); rays=np.tile([0.,0.,1.],(10,1))
        ext=[(np.eye(3),np.zeros(3)),(np.eye(3),np.array([.1,0,0]))]
        result=uncertainty(points,rays,np.zeros(10,dtype=int),ext,np.eye(3),np.zeros(3),np.ones(10,dtype=bool))
        self.assertFalse(result['valid'])
        self.assertEqual(result['reason'],'rank-deficient pose geometry')


if __name__=='__main__': unittest.main()
