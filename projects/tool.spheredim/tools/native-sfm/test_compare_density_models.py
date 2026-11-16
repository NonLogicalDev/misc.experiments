import math
import unittest
import numpy as np
import compare_density_models as d

class DensityComparisonTests(unittest.TestCase):
    def test_world_rotation_alignment(self):
        theta=.3;Q=np.array([[math.cos(theta),-math.sin(theta),0],[math.sin(theta),math.cos(theta),0],[0,0,1.]])
        a={'cam0/f':(np.eye(3),np.zeros(3))};b={'cam0/f':(Q.T,np.zeros(3))}
        result=d.rotation_alignment(a,b,['cam0/f'])
        np.testing.assert_allclose(result,Q.T,atol=1e-12)
        np.testing.assert_allclose(a['cam0/f'][0]@result@b['cam0/f'][0].T,np.eye(3),atol=1e-12)
    def test_spherical_residual_and_missing_point(self):
        poses={'im':(np.eye(3),np.zeros(3))};points={7:np.array([0.,0.,2.])}
        self.assertAlmostEqual(d.residual('im',(512.,256.),7,poses,points,1024,512),0.,places=8)
        with self.assertRaisesRegex(ValueError,'Missing 3D point'):d.residual('im',(512.,256.),8,poses,points,1024,512)

if __name__=='__main__':unittest.main()
