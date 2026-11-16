import copy
import importlib.util
from pathlib import Path
import unittest
import numpy as np

spec=importlib.util.spec_from_file_location('baselines',Path(__file__).with_name('prepare_rig_baselines.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class RigBaselinesTest(unittest.TestCase):
    def test_center_transform_and_scaling(self):
        q={'w':1,'x':0,'y':0,'z':0}
        cal={'lenses':[{'orientation':q,'translation':[0,0,0]}, {'orientation':q,'translation':[2,0,0]}]}
        rig={'rigs':[{'members':[{'prefix':'cam0','fixed':True,'refine':'none','translation':[0,0,0]},
                {'prefix':'cam1','fixed':True,'refine':'none','rotation':[1,0,0,0],'translation':[0,0,1]}]}]}
        fit={'baseline_direction':[1,0,0]}
        original=copy.deepcopy(rig)
        fitted,metadata,info=m.derive(cal,rig,fit)
        self.assertEqual(rig,original)
        np.testing.assert_allclose(fitted['rigs'][0]['members'][1]['translation'],[0,0,2])
        np.testing.assert_allclose(metadata['rigs'][0]['members'][1]['translation'],[0,0,2])
        self.assertAlmostEqual(info['metadata_baseline_norm'],2)
        self.assertAlmostEqual(info['angle_to_fitted_direction_degrees'],0)

    def test_nonidentity_orientation_and_camera_rotation(self):
        h=2**-.5
        cal={'lenses':[{'orientation':{'w':h,'x':0,'y':0,'z':h},'translation':[0,0,0]},
                       {'orientation':{'w':1,'x':0,'y':0,'z':0},'translation':[0,2,0]}]}
        R=m.quaternion_matrix([h,0,0,h])
        fitted_direction=np.array([1.,0.,0.])
        t=-R@m.BODY_FROM_CV.T@fitted_direction
        rig={'rigs':[{'members':[{'prefix':'cam0','fixed':True,'refine':'none','translation':[0,0,0]},
                    {'prefix':'cam1','fixed':True,'refine':'none','rotation':[h,0,0,h],'translation':t.tolist()}]}]}
        _,metadata,info=m.derive(cal,rig,{'baseline_direction':fitted_direction.tolist()})
        np.testing.assert_allclose(info['metadata_center_body'],[2,0,0],atol=1e-12)
        np.testing.assert_allclose(metadata['rigs'][0]['members'][1]['translation'],2*t,atol=1e-12)

    def test_nonzero_reference_and_nonmatching_fitted_rejected(self):
        q={'w':1,'x':0,'y':0,'z':0}
        cal={'lenses':[{'orientation':q,'translation':[0,0,0]}, {'orientation':q,'translation':[1,0,0]}]}
        rig={'rigs':[{'members':[{'prefix':'cam0','fixed':True,'refine':'none','translation':[0,0,0]},
                {'prefix':'cam1','fixed':True,'refine':'none','rotation':[1,0,0,0],'translation':[1,0,0]}]}]}
        with self.assertRaisesRegex(ValueError,'fitted direction'):m.derive(cal,rig,{'baseline_direction':[1,0,0]})

if __name__=='__main__': unittest.main()
