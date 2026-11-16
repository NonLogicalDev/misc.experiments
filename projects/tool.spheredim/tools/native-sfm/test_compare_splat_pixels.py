import unittest
import json
import tempfile
from pathlib import Path
import cv2
import numpy as np
import compare_splat_pixels as c

class PixelComparisonTests(unittest.TestCase):
    def test_half_error_uses_error_not_decibel_ratio(self):
        ref=np.zeros((2,4,3),np.uint8);mask=np.full((2,4),255,np.uint8)
        base=ref.copy();base[:]=20
        new=ref.copy();new[:]=10
        result=c.pool([c.score(ref,base,new,mask,mask)])
        self.assertAlmostEqual(result['spherical_mse_ratio'],.25)
        self.assertAlmostEqual(result['psnr_gain_db'],6.020599913)
        self.assertTrue(result['half_error_gate_passed'])
    def test_mask_intersection_scores_both_on_same_pixels(self):
        ref=np.zeros((2,4,3),np.uint8);base=ref.copy();new=ref.copy()
        base[:,0]=255;new[:,1]=255
        oldmask=np.full((2,4),255,np.uint8);newmask=oldmask.copy();newmask[:,0]=0
        result=c.score(ref,base,new,oldmask,newmask)
        self.assertEqual(result['baseline']['pixel_squared_error_sum'],0)
        self.assertEqual(result['candidate']['pixel_squared_error_sum'],2)
        self.assertEqual(result['mask_changed_pixels'],2)
    def test_pool_uses_actual_area_not_average_frame_psnr(self):
        rows=[{'common_spherical_area':1,'baseline_spherical_area':1,'common_valid_pixels':1,'baseline':{'spherical_squared_error_sum':.01,'pixel_squared_error_sum':.01},'candidate':{'spherical_squared_error_sum':.001,'pixel_squared_error_sum':.001}},
              {'common_spherical_area':9,'baseline_spherical_area':9,'common_valid_pixels':9,'baseline':{'spherical_squared_error_sum':.9,'pixel_squared_error_sum':.9},'candidate':{'spherical_squared_error_sum':.9,'pixel_squared_error_sum':.9}}]
        result=c.pool(rows)
        self.assertAlmostEqual(result['baseline']['pooled_spherical_mse'],.091)
        self.assertFalse(result['half_error_gate_passed'])
    def test_empty_and_incompatible_inputs_fail(self):
        image=np.zeros((2,4,3),np.uint8);mask=np.zeros((2,4),np.uint8)
        with self.assertRaises(ValueError):c.score(image,image,image,mask,mask)
        with self.assertRaises(ValueError):c.score(image,image,image[:,:3],mask,mask)
        with self.assertRaises(ValueError):c.pool([])
    def test_perfect_baseline_does_not_claim_twofold_gain(self):
        image=np.zeros((2,4,3),np.uint8);mask=np.full((2,4),255,np.uint8)
        result=c.pool([c.score(image,image,image,mask,mask)])
        self.assertIsNone(result['spherical_mse_ratio']);self.assertFalse(result['half_error_gate_passed'])
    def test_coverage_rejects_a_win_from_excluding_pixels(self):
        ref=np.zeros((2,4,3),np.uint8);base=np.full_like(ref,20);new=np.full_like(ref,10)
        oldmask=np.full((2,4),255,np.uint8);newmask=oldmask.copy();newmask[:,0]=0
        result=c.pool([c.score(ref,base,new,oldmask,newmask)])
        self.assertTrue(result['spherical_error_halved']);self.assertFalse(result['coverage_gate_passed']);self.assertFalse(result['half_error_gate_passed'])
    def test_spherical_only_improvement_is_not_full_gate(self):
        row={'common_spherical_area':1,'baseline_spherical_area':1,'common_valid_pixels':1,
             'baseline':{'spherical_squared_error_sum':.1,'pixel_squared_error_sum':.1},
             'candidate':{'spherical_squared_error_sum':.04,'pixel_squared_error_sum':.09}}
        result=c.pool([row]);self.assertTrue(result['spherical_error_halved']);self.assertFalse(result['half_error_gate_passed'])
    def test_evaluation_verifies_source_mask_and_camera_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);name='eval_000000_cam0.png';image=np.full((4,8,3),128,np.uint8);mask=np.full((4,8),255,np.uint8)
            for label in ('base','new'):
                data=root/label;run=data/'run'
                for folder in ('images','masks','sparse/0','run'):(data/folder).mkdir(parents=True,exist_ok=True)
                row={'name':name,'source_name':'cam0/frame_000000.png','source_frame':0,'lens':'cam0','timestamp_microseconds':0,'source_packet_pts':[0,0]}
                (data/'manifest.json').write_text(json.dumps({'frames':[row],'heldout_evaluation_order':[name]}))
                (run/'config.json').write_text(json.dumps({'data':str(data)}))
                (data/'sparse/0/cameras.txt').write_text('1 EQUIRECTANGULAR 8 4 8 4\n')
                # Different estimates/gauges are expected in the density comparison.
                (data/'sparse/0/images.txt').write_text(label+' pose provenance\n')
                for path,array in [(data/'images'/name,image),(data/'masks'/name,mask),(run/'eval-gt-00000.png',image),(run/'eval-mask-00000.png',mask),(run/'eval-render-00000.png',image-20 if label=='base' else image-10)]:self.assertTrue(cv2.imwrite(str(path),array))
            args=(root/'base/manifest.json',root/'base/run',root/'new/manifest.json',root/'new/run')
            self.assertTrue(c.evaluate(*args)['summary']['half_error_gate_passed'])
            changed=image.copy();changed[0,0]=0;cv2.imwrite(str(root/'new/images'/name),changed)
            with self.assertRaisesRegex(ValueError,'Source pixels differ'):c.evaluate(*args)
            cv2.imwrite(str(root/'new/images'/name),image)
            changed_mask=mask.copy();changed_mask[0,0]=0;cv2.imwrite(str(root/'new/run/eval-mask-00000.png'),changed_mask)
            with self.assertRaisesRegex(ValueError,'Saved validity differs'):c.evaluate(*args)
            cv2.imwrite(str(root/'new/run/eval-mask-00000.png'),mask)
            (root/'new/sparse/0/cameras.txt').write_text('1 EQUIRECTANGULAR 16 8 16 8\n')
            with self.assertRaisesRegex(ValueError,'intrinsics differ'):c.evaluate(*args)
if __name__=='__main__':unittest.main()
