import unittest
import numpy as np
import audit_readout_residual as audit


class TestReadout(unittest.TestCase):
    def test_independent_rotating_camera_residual_sign(self):
        lon = np.linspace(-1, 1, 60)
        lat = np.linspace(-0.5, 0.5, 60)
        rays = np.column_stack((np.sin(lon)*np.cos(lat), np.sin(lat), np.cos(lon)*np.cos(lat)))
        xy = np.column_stack(((lon/(2*np.pi)+0.5)*2048, (lat/np.pi+0.5)*1024))
        omega = np.array([0.01, -0.02, 0.03])
        times = np.linspace(-0.004, 0.004, len(rays))
        norm = np.linalg.norm(omega)
        axis = omega / norm
        angles = norm * times
        rotated = (rays*np.cos(angles)[:,None] + np.cross(axis, rays)*np.sin(angles)[:,None]
                   + np.outer(1-np.cos(angles), axis)*(rays@axis)[:,None])
        observed, _ = audit.signed_residual(rotated, np.eye(3), np.zeros(3), xy, 2048, 1024)
        design = audit.rotation_design(rays)
        predicted = np.einsum('nij,j,n->ni', design, omega, times)
        self.assertLess(np.max(np.abs(observed-predicted)), 2e-6)
        nuisance = np.einsum('nij,j->ni', design, [0.03, 0.02, -0.01])
        y, x = audit.remove_rotation(observed+nuisance, predicted, design)
        self.assertAlmostEqual(audit.robust_amplitude(x, y), 1, places=3)
        self.assertLess(np.mean((y-x)**2), np.mean((y+x)**2))

    def test_stationary_and_constant_rotation_removed(self):
        rays = np.array([[0,0,1],[1,0,0],[0,1,0],[-1,0,0],[0,-1,0]],float)
        design = audit.rotation_design(rays)
        residual = np.einsum('nij,j->ni', design, [0.2,-0.1,0.4])
        y, x = audit.remove_rotation(residual, np.zeros_like(residual), design)
        self.assertTrue(np.allclose(y, 0, atol=1e-10))
        self.assertTrue(np.allclose(x, 0))
        self.assertIsNone(audit.robust_amplitude(x, y))

    def test_outlier_nuisance_invariance(self):
        lon = np.linspace(-1.0, 1.0, 100)
        lat = np.linspace(-0.5, 0.5, 100)
        rays = np.column_stack((np.sin(lon)*np.cos(lat), np.sin(lat), np.cos(lon)*np.cos(lat)))
        design = audit.rotation_design(rays)
        predictor = np.einsum('nij,j,n->ni', design, [0.01, -0.02, 0.03], np.linspace(-0.004, 0.004, 100))
        residual = 0.2*predictor
        residual[7] += [4.0, -5.0]
        nuisance = np.einsum('nij,j->ni', design, [0.1, -0.07, 0.02])
        y1, x1 = audit.remove_rotation(residual, predictor, design)
        y2, x2 = audit.remove_rotation(residual+nuisance, predictor, design)
        self.assertTrue(np.allclose(y1, y2, atol=1e-9))
        self.assertTrue(np.allclose(x1, x2, atol=1e-9))

    def test_source_coordinate_pinhole_limit_and_singular_denominator(self):
        lens = {
            'orientation': {'w': 1, 'x': 0, 'y': 0, 'z': 0},
            'xi': 0, 'distortion_coefficients': [0.0]*13,
            'cx': 50, 'cy': 50, 'fx': 20, 'fy': 20,
            'canvas_width': 200, 'canvas_height': 100,
        }
        rays = np.array([[0., 0., 1.], [0.5, 0., 1.], [1., 0., 0.]])
        x, y, valid = audit.source_coordinates(rays, lens, 0, 100, 100)
        self.assertTrue(np.allclose(x[:2], [50, 60]))
        self.assertTrue(np.allclose(y[:2], [50, 50]))
        self.assertEqual(valid.tolist(), [True, True, False])
        self.assertTrue(np.isnan(x[2]))

    def test_gyro_integral(self):
        t = np.array([0.,1000.,2000.])
        integral = np.array([[0,0,0],[0,0,.001],[0,0,.002]])
        result = audit.integrate(t, integral, np.array([500.,1500.]))
        self.assertTrue(np.allclose(result[:,2], [.0005,.0015]))


if __name__ == '__main__':
    unittest.main()
