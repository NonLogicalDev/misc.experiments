import importlib.util,unittest,tempfile
from pathlib import Path
import cv2,numpy as np
from scipy.spatial.transform import Rotation
spec=importlib.util.spec_from_file_location('rig',Path(__file__).resolve().parent/'prepare_rig.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class RigTests(unittest.TestCase):
 def test_cv_basis_and_known_landmark(self):
  u=1.1;v=.3;cv=np.array([np.cos(v)*np.sin(u-np.pi),np.sin(v),np.cos(v)*np.cos(u-np.pi)]);body=np.array([np.cos(v)*np.cos(u),-np.cos(v)*np.sin(u),-np.sin(v)])
  np.testing.assert_allclose(m.BODY_FROM_CV@cv,body,atol=1e-12)
  rotation=Rotation.from_euler('xyz',[.03,-.02,.01]).as_matrix();b=np.array([1.,0.,0.]);R,t=m.rig_extrinsic(rotation,b)
  point=np.array([2.,4.,5.]);world_cv=m.BODY_FROM_CV.T@point;expected=m.BODY_FROM_CV.T@rotation.T@(point-b)
  np.testing.assert_allclose(R@world_cv+t,expected,atol=1e-12);np.testing.assert_allclose(-R.T@t,m.BODY_FROM_CV.T@b,atol=1e-12)
 def test_mask_inverse_orientation(self):
  keep=np.ones((16,32),bool);keep[6:10,4:8]=False;Q=Rotation.from_euler('z',90,degrees=True).as_matrix();body=np.array([[1.,0.,0.]])
  np.testing.assert_allclose((body@Q)[0], [0,-1,0],atol=1e-12)
  ray=m.body_rays(64,32);out=m.operator_body_keep(keep,Q)
  expected=m.keep_sample_all_neighbors(keep,ray@Q).reshape(16,2,32,2).all(axis=(1,3));np.testing.assert_array_equal(out,expected);self.assertTrue(np.any(~out));np.testing.assert_array_equal(out,np.roll(m.operator_body_keep(keep,np.eye(3)),-8,axis=1))
 def test_support_guard_wrap_and_split(self):
  keep=np.ones((256,512),bool);keep[100,0]=False;guard=m.feature_guard(keep,3)
  self.assertFalse(guard[100,511]);self.assertFalse(guard[100,0]);self.assertTrue(guard[100,20]);train,ev=m.spatial_feature_split(guard)
  self.assertFalse(np.any(train&ev));self.assertFalse(np.any((train|ev)&~guard))
  y,x=np.where(ev);self.assertTrue(np.all(((x//128+2*(y//128))%5)==0));self.assertTrue(np.all((x%128>=16)&(x%128<112)&(y%128>=16)&(y%128<112)))
  self.assertTrue(np.all(((np.where(train)[1]//128+2*(np.where(train)[0]//128))%5)!=0))
 def test_256_tile_split(self):
  valid=np.ones((512,1024),bool);train,evaluation=m.spatial_feature_split(valid,256,16)
  self.assertFalse(np.any(train&evaluation));y,x=np.where(evaluation)
  self.assertTrue(np.all((x//256+2*(y//256))%5==0));self.assertTrue(np.all((x%256>=16)&(x%256<240)&(y%256>=16)&(y%256<240)))
 def test_per_lens_blocks_are_disjoint_and_equal_area(self):
  valid=np.ones((512,1024),bool);masks=[]
  for lens,left in [('cam0',512),('cam1',768)]:
   train,evaluation=m.per_lens_feature_split(valid,lens);y,x=np.where(evaluation)
   self.assertFalse(np.any(train&evaluation));self.assertEqual(int(evaluation.sum()),224*224)
   self.assertTrue(np.all((x>=left+16)&(x<left+240)&(y>=272)&(y<496)))
   self.assertFalse(np.any(train[256:512,left:left+256]));masks.append(evaluation)
  self.assertFalse(np.any(masks[0]&masks[1]))
 def test_arbitrary_sorted_frame_coverage(self):
  for count in (2,17):
   frames=[{'frame':n*7+3} for n in range(count)]; available={x['frame']:{} for x in frames}
   m.validate_frames(frames,available,available)
   with self.assertRaises(ValueError):m.validate_frames(frames[::-1],available,available)
   with self.assertRaises(ValueError):m.validate_frames(frames+[frames[-1]],available,available)
   with self.assertRaises(ValueError):m.validate_frames(frames,{},available)
   with self.assertRaises(ValueError):m.validate_frames(frames,available,{})
 def test_no_holdout_and_paginated_sheets(self):
  guarded=np.array([[True,False],[True,True]])
  for lens in ('cam0','cam1'):
   train,evaluation=m.split_features(guarded,lens,'none',128)
   np.testing.assert_array_equal(train,guarded);self.assertFalse(evaluation.any())
  with tempfile.TemporaryDirectory() as tmp:
   directory=Path(tmp);tile=np.ones((8,16,3),np.uint8)
   m.write_sheet_page(directory,'cam0',[tile]*16,1);m.write_sheet_page(directory,'cam0',[tile],2)
   self.assertEqual(cv2.imread(str(directory/'cam0-review-001.png')).shape,(32,64,3))
   self.assertEqual(cv2.imread(str(directory/'cam0-review-002.png')).shape,(8,64,3))
 def test_invalid_rig_rejected(self):
  with self.assertRaises(ValueError):m.rig_extrinsic(np.eye(3),[2,0,0])
if __name__=='__main__':unittest.main()
