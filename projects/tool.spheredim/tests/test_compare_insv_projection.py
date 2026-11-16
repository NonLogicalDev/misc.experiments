import importlib.util
from pathlib import Path
import unittest
import numpy as np

spec=importlib.util.spec_from_file_location('projection',Path(__file__).resolve().parents[1]/'scripts/compare_insv_projection.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class ProjectionComparisonTest(unittest.TestCase):
 def test_remaps_same_source_pixel_and_identity(self):
  lens={'xi':2.,'cx':2600.,'cy':2600.,'fx':4200.,'fy':4200.,'orientation':{'w':1.,'x':0.,'y':0.,'z':0.},'distortion_coefficients':[.24,1.2,.5,-6.,0.,-.001,.001,.006,.002,-.006,-.001,-.007,-.003]}
  theta=np.deg2rad(np.array([10.,45.,85.,90.,100.])); phi=np.array([.2,1.,2.,4.,5.]); rays=m.local_rays(theta,phi)
  same,ok,error=m.remap_rays(rays,lens,target_model='upstream');self.assertTrue(ok.all());np.testing.assert_allclose(same,rays,atol=1e-10)
  alternate,ok,error=m.remap_rays(rays,lens,target_model='thin_prism');self.assertTrue(ok.all());np.testing.assert_allclose(m.project_local(alternate,lens,'thin_prism'),m.project_local(rays,lens,'upstream'),atol=.01)

if __name__=='__main__':unittest.main()
