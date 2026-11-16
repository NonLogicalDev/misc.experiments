import unittest
import numpy as np
from scipy.spatial.transform import Rotation
from rig_pose import fit_rig_pose


class RigPoseTest(unittest.TestCase):
    def test_known_rig_pose_with_noise_and_outliers(self):
        rng = np.random.default_rng(42)
        points = rng.uniform([-3, -2, 3], [3, 2, 8], size=(100, 3))
        members = np.arange(len(points)) % 2
        ext = [(np.eye(3), np.zeros(3)), (Rotation.from_rotvec([.01, -.02, .03]).as_matrix(), np.array([.01, -.02, .08]))]
        truth_r = Rotation.from_rotvec([.07, -.05, .02]).as_matrix()
        truth_t = np.array([.1, -.2, .15])
        rig = points @ truth_r.T + truth_t
        camera = np.array([ext[m][0] @ p + ext[m][1] for p, m in zip(rig, members)])
        bearings = camera / np.linalg.norm(camera, axis=1)[:, None]
        bearings += rng.normal(0, .0002, bearings.shape)
        bearings /= np.linalg.norm(bearings, axis=1)[:, None]
        bearings[:15] = rng.normal(size=(15, 3))
        bearings[:15] /= np.linalg.norm(bearings[:15], axis=1)[:, None]
        initial = (Rotation.from_rotvec([.08, -.04, .01]).as_matrix(), truth_t + [.03, -.02, .03])
        r, t, inliers, success = fit_rig_pose(points, bearings, members, ext, initial, threshold_radians=.003)
        self.assertTrue(success)
        self.assertLess(np.linalg.norm(Rotation.from_matrix(r @ truth_r.T).as_rotvec()), .003)
        self.assertLess(np.linalg.norm(t - truth_t), .02)
        self.assertGreaterEqual(inliers[15:].sum(), 80)
        self.assertLessEqual(inliers[:15].sum(), 1)


if __name__ == '__main__':
    unittest.main()

class RegistrationGateTest(unittest.TestCase):
    def test_rejects_one_lens_and_duplicate_landmarks(self):
        from rig_pose import validate_registration
        result = validate_registration([1,1,1,1], [10,10,11,11], [0,0,0,0],
            [[5,5],[300,5],[5,200],[300,200]], [1,2,3,4], min_landmarks=3,
            min_per_lens=1, min_regions_per_lens=1, min_source_timestamps=2)
        self.assertFalse(result['accepted'])
        self.assertEqual(result['distinct_landmarks'], 2)
        self.assertEqual(result['distinct_landmarks_per_lens'], [2,0])

    def test_accepts_spread_support_from_both_lenses(self):
        from rig_pose import validate_registration
        result = validate_registration([1,1,1,1], [10,11,12,13], [0,0,1,1],
            [[5,5],[300,200],[5,5],[300,200]], [1,2,3,4], min_landmarks=4,
            min_per_lens=2, min_regions_per_lens=2, min_source_timestamps=2)
        self.assertTrue(result['accepted'])

class RigValidationTest(unittest.TestCase):
    def test_checks_nonzero_and_constant_extrinsics(self):
        from rig_pose import validate_fixed_rig
        ext = [(np.eye(3), np.zeros(3)), (np.eye(3), np.array([.1, 0, 0]))]
        poses = [((np.eye(3), np.array([1.,2.,3.])), (np.eye(3), np.array([1.1,2.,3.])))]
        report = validate_fixed_rig(poses, ext, rotation_tolerance_radians=1e-7, translation_tolerance=1e-7)
        self.assertAlmostEqual(report['baseline'], .1)
        with self.assertRaisesRegex(ValueError, 'nonzero'):
            validate_fixed_rig(poses, [ext[0], ext[0]], rotation_tolerance_radians=1e-7, translation_tolerance=1e-7)
        with self.assertRaisesRegex(ValueError, 'disagree'):
            validate_fixed_rig([((np.eye(3), np.zeros(3)), (np.eye(3), np.array([.2, 0, 0])))], ext, rotation_tolerance_radians=1e-7, translation_tolerance=1e-7)
