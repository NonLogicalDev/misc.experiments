import tempfile
import unittest
from pathlib import Path

from prepare_poster_seed_fit import cloud_info


class PosterSeedTests(unittest.TestCase):
    def test_scale_uses_only_supplied_points_and_rejects_uniform_color(self):
        with tempfile.TemporaryDirectory() as directory:
            cloud = Path(directory)/'points.ply'
            header = ('ply\nformat ascii 1.0\nelement vertex 2\n'
                      'property float x\nproperty float y\nproperty float z\n'
                      'property uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n')
            cloud.write_text(header + '0 0 0 1 2 3\n2 0 0 4 5 6\n')
            result = cloud_info(cloud)
            self.assertEqual(result['points'], 2)
            self.assertAlmostEqual(result['scale_min_median_max'][1], .7)
            cloud.write_text(header + '0 0 0 1 2 3\n2 0 0 1 2 3\n')
            with self.assertRaisesRegex(ValueError, 'uniform'):
                cloud_info(cloud)
            cloud.write_text(header + '0 0 0 1 2 3\n0 0 0 4 5 6\n')
            with self.assertRaisesRegex(ValueError, 'Duplicate XYZ'):
                cloud_info(cloud)


if __name__ == '__main__':
    unittest.main()
