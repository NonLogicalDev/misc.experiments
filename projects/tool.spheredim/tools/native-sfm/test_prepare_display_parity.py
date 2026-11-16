import unittest
import numpy as np
import prepare_display_parity as parity


class DisplayParityTest(unittest.TestCase):
    def test_center_ray_and_opengl_basis(self):
        basis = parity.camera_basis(4, 2, 8, 4)
        np.testing.assert_allclose(basis, np.eye(3), atol=1e-12)
        np.testing.assert_allclose(basis.T @ basis, np.eye(3), atol=1e-12)
        np.testing.assert_allclose(basis @ np.diag([1, -1, -1]), np.diag([1, -1, -1]))

    def test_invalid_source_tap_masks_output(self):
        image = np.full((4, 8, 3), 180, np.uint8)
        mask = np.full((4, 8), 255, np.uint8)
        view, valid, _, _ = parity.project_view(image, mask, (4, 2), 1, 55)
        self.assertTrue(valid[0, 0])
        self.assertTrue(np.all(view[0, 0] == 180))
        mask[1, 3] = 0
        view, valid, _, _ = parity.project_view(image, mask, (4, 2), 1, 55)
        self.assertFalse(valid[0, 0])
        self.assertTrue(np.all(view[0, 0] == 0))


if __name__ == '__main__':
    unittest.main()
