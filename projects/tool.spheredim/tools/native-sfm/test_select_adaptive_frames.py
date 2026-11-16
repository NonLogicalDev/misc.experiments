import unittest
from unittest.mock import patch
import numpy as np
from scipy.spatial.transform import Rotation
import select_adaptive_frames as a
import compare_rigs
import prepare_rig


class AdaptiveTests(unittest.TestCase):
    def test_bearings_match_sfm_feature_coordinate_convention(self):
        coords=np.array([[0,0],[77.25,33.5],[512,256],[980,470]],float)
        expected=np.stack([prepare_rig.BODY_FROM_CV@compare_rigs.ray(x,y,1024,512) for x,y in coords])
        np.testing.assert_allclose(a.bearings(coords,1024,512),expected,atol=1e-12)

    def test_known_rotation_yields_zero_residual(self):
        xy=np.array([[100,100],[300,200],[600,300],[800,400]],float)
        angle=45
        # The camera's positive world yaw shifts the same bearing to higher ERP longitude.
        shifted=xy.copy();shifted[:,0]+=angle*1024/360
        r=Rotation.from_euler('z',angle,degrees=True).as_matrix()
        self.assertLess(float(np.max(a.residual_degrees(xy,shifted,np.eye(3),r))),1e-5)

    def test_timestamp_mismatch_rejected(self):
        frame={'source_frame':1,'timestamp_microseconds':1000000,'fused_row':{'frame':'1','video_pts_s':'1.0'},'source_packet_pts':[{'stream':0,'pts':1000,'time_base':'1/1000'},{'stream':1,'pts':1000,'time_base':'1/1000'}]}
        a.validate_timestamp(frame)
        frame['source_packet_pts'][1]['pts']=1001
        with self.assertRaisesRegex(ValueError,'timestamp mismatch'): a.validate_timestamp(frame)

    def test_missing_overlap_is_unknown_and_not_novelty(self):
        blank=(np.zeros((0,2)),None)
        self.assertEqual(a.matched_novelty(blank,blank,np.eye(3),np.eye(3))['status'],'insufficient_overlap')
        candidate={'quality_eligible':True,'novelty_degrees':None,'step':1,'total_score':None}
        self.assertEqual(a.choose([candidate],False),(None,None))
        self.assertEqual(a.choose([candidate],True),(None,'max_gap_insufficient_measurable_overlap'))
        bad={'quality_eligible':False,'novelty_degrees':2,'step':1,'total_score':1}
        self.assertIsNone(a.choose([bad],True)[0])

    def test_low_contrast_lens_becomes_unknown(self):
        image=np.full((64,64),120,np.uint8);mask=np.ones_like(image,bool)
        normalized,valid=a.scene_or_unknown(image,mask)
        self.assertFalse(valid.any())
        self.assertFalse(normalized.any())
        textured=np.tile(np.where(np.arange(64)%8<4,50,180).astype(np.uint8),(64,1))
        result,valid=a.scene_or_unknown(textured,mask)
        self.assertTrue(valid.all())
        self.assertGreater(int(result.max()),int(result.min()))

    def test_textureless_lens_is_unknown_and_missing_overlap_fails(self):
        ok={'status':'ok'};missing={'status':'insufficient_overlap'}
        self.assertTrue(a.quality_gate([90,None],[100,None],[ok,missing])[0])
        self.assertFalse(a.quality_gate([90,None],[100,None],[missing,ok])[0])
        self.assertTrue(a.quality_gate([90,40],[100,100],[ok,ok])[0])
        self.assertTrue(a.quality_gate([90,40],[100,100],[ok,ok])[2])
        self.assertFalse(a.quality_gate([None,None],[None,None],[ok,ok])[0])

    def test_later_batch_does_not_reclassify_earlier_candidate(self):
        def candidate(frame):
            return {'frame':frame,'matches':[{'status':'ok'},{'status':'ok'}],'novelty_degrees':1.0,'elapsed_seconds_from_reference':1.0}
        item={'images':[None,None],'masks':[np.ones((32,32),bool),np.ones((32,32),bool)]}
        early=candidate(1);late=candidate(2)
        with patch.object(a.sharp,'score_window',side_effect=[[{'score':20},{'score':20}],[{'score':20},{'score':20}],[{'score':100},{'score':20}],[{'score':100},{'score':20}]]):
            a.score_batch([early],[item],item); snapshot=dict(early)
            a.score_batch([late],[item],item)
        self.assertEqual(early,snapshot)
        self.assertTrue(early['quality_eligible'])
        self.assertEqual(early['quality_batch']['lens_maxima'],[20,20])

    def test_invalid_candidate_does_not_hide_other_lens_scores(self):
        def candidate(frame):
            return {'frame':frame,'matches':[{'status':'ok'},{'status':'ok'}],'novelty_degrees':1.,'elapsed_seconds_from_reference':1.}
        valid=np.ones((32,32),bool);invalid=np.zeros((32,32),bool)
        good={'images':[None,None],'masks':[valid,valid]}
        bad={'images':[None,None],'masks':[invalid,valid]}
        first,second=candidate(1),candidate(2)
        with patch.object(a.sharp,'score_window',side_effect=[[{'score':20},{'score':20}],[{'score':20},{'score':20},{'score':20}]]):
            a.score_batch([first,second],[good,bad],good)
        self.assertEqual(first['sharpness'][0],20)
        self.assertIsNone(second['sharpness'][0])
        self.assertTrue(first['quality_eligible'])
        self.assertTrue(second['quality_eligible'])

    def test_low_relative_sharpness_can_win_with_strong_information(self):
        near={'quality_eligible':True,'novelty_degrees':2.0,'step':1,'total_score':a.rank_components(.70,2,.1)[2]}
        far={'quality_eligible':True,'novelty_degrees':.5,'step':2,'total_score':a.rank_components(1,.5,.3)[2]}
        self.assertEqual(a.choose([near,far],False)[0],near)

    def test_soft_age_penalty_is_bounded_and_near_can_win(self):
        def candidate(step,novelty,dt):
            return {'step':step,'novelty_degrees':novelty,'quality_eligible':True,'total_score':a.rank_components(1,novelty,dt)[2]}
        near=candidate(1,.6,.1);far=candidate(6,.6,1)
        self.assertEqual(a.choose([near,far],False)[0],far)
        strong=candidate(1,2,.1)
        self.assertEqual(a.choose([strong,far],False)[0],strong)
        near_penalty=a.rank_components(1,.6,.1)[1]
        far_penalty=a.rank_components(1,.6,1)[1]
        self.assertGreater(near_penalty,far_penalty)
        self.assertGreaterEqual(far_penalty,0)
        self.assertLessEqual(near_penalty,.15)
        before=a.rank_components(1,.6,a.elapsed_seconds(0,100000))[1]
        after_reset=a.rank_components(1,.6,a.elapsed_seconds(1000000,1100000))[1]
        self.assertEqual(before,after_reset)
        self.assertIsNone(a.rank_components(1,None,.1)[2])


if __name__=='__main__':unittest.main()
