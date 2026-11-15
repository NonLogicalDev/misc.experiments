import importlib.util
import unittest
from pathlib import Path
import numpy as np

spec = importlib.util.spec_from_file_location('evaluate', Path(__file__).with_name('evaluate.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.truth = []
        self.poses = {'frames': []}
        self.imported = {}
        for i in range(4):
            m = np.eye(4)
            m[:3, 3] = [i, (i % 2) * 0.5, 0]
            # At panorama center the Blender camera ray is its local -Z axis.
            points = [[512, 256, i, (i % 2) * 0.5, -4]]
            self.truth.append({'world_from_blender_camera': m.tolist(), 'visible_world_points': points})
            self.poses['frames'].append({'frame': i, 'world_from_camera': m[:3].tolist()})
            self.imported[str(i)] = m.tolist()

    def test_exact_poses_have_zero_error(self):
        report = module.evaluate(self.truth, self.poses, self.imported)
        self.assertLess(report['position_rmse_percent_path'], 1e-10)
        self.assertLess(report['image_rms_percent'], 1e-10)
        self.assertEqual(report['registered'], 4)

    def test_wrong_orientation_increases_image_error(self):
        m = np.array(self.imported['1'])
        a = 0.2
        m[:3, :3] = [[np.cos(a), 0, np.sin(a)], [0, 1, 0], [-np.sin(a), 0, np.cos(a)]]
        self.imported['1'] = m.tolist()
        self.assertGreater(module.evaluate(self.truth, self.poses, self.imported)['image_rms_percent'], 1)

    def test_missing_frames_remain_visible_in_coverage(self):
        self.poses['frames'][0]['world_from_camera'] = None
        report = module.evaluate(self.truth, self.poses, self.imported)
        self.assertEqual((report['registered'], report['sampled']), (3, 4))


if __name__ == '__main__':
    unittest.main()
