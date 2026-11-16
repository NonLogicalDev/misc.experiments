import unittest
import numpy as np
import compare_splat_resolutions as c

class ResolutionComparisonTests(unittest.TestCase):
 def setUp(self):
  self.lo=np.full((512,1024,3),32,np.uint8);self.hi=np.full((1024,2048,3),32,np.uint8);self.lm=np.full((512,1024),255,np.uint8);self.hm=np.full((1024,2048),255,np.uint8)
 def test_camera_model_and_scaled_intrinsics(self):
  low='1 EQUIRECTANGULAR 1024 512 1024 512\n2 EQUIRECTANGULAR 1024 512 1024 512\n';high='1 EQUIRECTANGULAR 2048 1024 2048 1024\n2 EQUIRECTANGULAR 2048 1024 2048 1024\n';c.validate_cameras(low,high)
  with self.assertRaisesRegex(ValueError,'camera model'):c.validate_cameras(low,high.replace('EQUIRECTANGULAR','PINHOLE',1))
  with self.assertRaisesRegex(ValueError,'intrinsics differ'):c.validate_cameras(low,high.replace('2048 1024 2048 1024','2048 1024 2047 1024',1))
 def test_estimated_pose_mode_is_opt_in_and_validates_camera_assignments(self):
  frames=[{'name':'eval_a.png','colmap_camera_id':1},{'name':'eval_b.png','colmap_camera_id':2}];order=[r['name'] for r in frames]
  low='1 1 0 0 0 0 0 0 1 eval_a.png\n\n2 1 0 0 0 0 0 0 2 eval_b.png\n\n'
  high=low.replace('0 0 0 1 eval_a','1 0 0 1 eval_a')
  with self.assertRaisesRegex(ValueError,'poses differ'):c.validate_pose_pair(low,high,frames,frames,order)
  c.validate_pose_pair(low,high,frames,frames,order,True)
  with self.assertRaisesRegex(ValueError,'Missing compared'):c.validate_pose_pair(low,high.split('2 1 0 0')[0],frames,frames,order,True)
  with self.assertRaisesRegex(ValueError,'Duplicate pose'):c.validate_pose_pair(low,high+high,frames,frames,order,True)
  with self.assertRaisesRegex(ValueError,'Wrong camera'):c.validate_pose_pair(low,high.replace('0 0 0 2 eval_b','0 0 0 1 eval_b'),frames,frames,order,True)
  with self.assertRaisesRegex(ValueError,'Invalid pose'):c.validate_pose_pair(low,high.replace('1 0 0 0 1 0 0 1 eval_a','2 0 0 0 1 0 0 1 eval_a'),frames,frames,order,True)
 def test_changed_capture_identity_rejected(self):
  row={'source_name':'cam0/f','source_frame':5,'lens':'cam0','timestamp_microseconds':12,'source_packet_pts':[1]}
  for key,value in [('source_name','cam1/f'),('source_frame',6),('lens','cam1'),('timestamp_microseconds',13),('source_packet_pts',[2])]:
   with self.subTest(key=key),self.assertRaisesRegex(ValueError,'Capture identity mismatch'):c.validate_capture_identity(row,{**row,key:value},'sample')

 def test_exact_reference_and_support(self):
  self.assertEqual(c.reduce_candidate(self.hi,self.hm,self.lo,self.lm,self.hi).shape,self.lo.shape)
 def test_changed_source_and_support_rejected(self):
  self.hi[0,0]=48
  with self.assertRaisesRegex(ValueError,'source differs'):c.reduce_candidate(self.hi,self.hm,self.lo,self.lm,self.hi)
  self.hi[0,0]=32;self.hm[0,0]=0
  with self.assertRaisesRegex(ValueError,'support differs'):c.reduce_candidate(self.hi,self.hm,self.lo,self.lm,self.hi)
if __name__=='__main__':unittest.main()
