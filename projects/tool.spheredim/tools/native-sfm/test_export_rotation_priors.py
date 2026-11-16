import importlib.util,unittest
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
spec=importlib.util.spec_from_file_location('prior',Path(__file__).resolve().parent/'export_rotation_priors.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class PriorTests(unittest.TestCase):
 def setUp(self):
  self.R=Rotation.from_euler('z',25,degrees=True).as_matrix();q=Rotation.from_matrix(self.R).as_quat();self.rig={'rigs':[{'members':[{'prefix':'cam0','fixed':True,'rotation':[1,0,0,0]},{'prefix':'cam1','fixed':True,'rotation':[q[3],q[0],q[1],q[2]]}]}]};self.dataset={'frames':[{'source_frame':15,'timestamp_microseconds':500500,'lenses':{'cam0':{'image_sha256':'a'},'cam1':{'image_sha256':'b'}}}]};self.fused=[{'frame':'15','video_pts_s':'0.5005','q_w':'1','q_x':'0','q_y':'0','q_z':'0'}]
 def test_known_basis_and_rig_relative_rotation(self):
  rows,_=m.build_priors(self.dataset,self.rig,self.fused,1.0);q=lambda r:Rotation.from_quat([r['qx'],r['qy'],r['qz'],r['qw']]).as_matrix();a,b=map(q,rows)
  np.testing.assert_allclose(a,m.BODY_FROM_CV,atol=1e-12);np.testing.assert_allclose(a.T@b,self.R.T,atol=1e-12);self.assertEqual([x['image'] for x in rows],['cam0/frame_000015.png','cam1/frame_000015.png'])
 def test_preserves_world_yaw(self):
  q=Rotation.from_euler('z',90,degrees=True).as_quat();self.fused[0].update(dict(zip(('q_x','q_y','q_z','q_w'),map(str,q))));rows,_=m.build_priors(self.dataset,self.rig,self.fused,1.0);r=rows[0];actual=Rotation.from_quat([r['qx'],r['qy'],r['qz'],r['qw']]).as_matrix();np.testing.assert_allclose(actual,Rotation.from_quat(q).as_matrix()@m.BODY_FROM_CV,atol=1e-12)
 def test_rejects_missing_duplicate_mismatch_and_sigma(self):
  with self.assertRaises(ValueError):m.build_priors(self.dataset,self.rig,[],1)
  with self.assertRaises(ValueError):m.build_priors(self.dataset,self.rig,self.fused*2,1)
  with self.assertRaises(ValueError):m.build_priors({'frames':self.dataset['frames']*2},self.rig,self.fused,1)
  with self.assertRaises(ValueError):m.build_priors(self.dataset,self.rig,self.fused,0)
  self.fused[0]['video_pts_s']='0.500501'
  with self.assertRaises(ValueError):m.build_priors(self.dataset,self.rig,self.fused,1)
if __name__=='__main__':unittest.main()
