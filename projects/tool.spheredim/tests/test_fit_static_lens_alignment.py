import importlib.util
from pathlib import Path
import unittest
import numpy as np
from scipy.spatial.transform import Rotation
spec=importlib.util.spec_from_file_location('alignment',Path(__file__).resolve().parents[1]/'scripts/fit_static_lens_alignment.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class AlignmentTest(unittest.TestCase):
    def test_shader_ray_axes(self):
        np.testing.assert_allclose(m.rays([[-.5,49.5],[49.5,49.5],[99.5,49.5]],200,100),[[1,0,0],[0,-1,0],[-1,0,0]],atol=1e-12)
    def test_recovers_rotation_with_outliers_and_holds_out_rays(self):
        rng=np.random.default_rng(7);a=rng.normal(size=(300,3));a/=np.linalg.norm(a,axis=1)[:,None]
        expected=Rotation.from_rotvec([.012,-.025,.018]).as_matrix();b=a@expected.T
        b[:65]=rng.normal(size=(65,3));b[:65]/=np.linalg.norm(b[:65],axis=1)[:,None]
        actual,mask=m.robust_fit(a[:240],b[:240],.25,trials=400)
        np.testing.assert_allclose(actual,expected,atol=1e-10)
        self.assertEqual(mask.sum(),175)
        self.assertLess(m.errors(a[240:],b[240:],actual).max(),1e-8)
        np.testing.assert_allclose((a[240:]@actual.T)@actual,a[240:],atol=1e-10)
    def test_refuses_sparse_correspondences(self):
        with self.assertRaises(ValueError):m.robust_fit(np.eye(3),np.eye(3))
if __name__=='__main__':unittest.main()
