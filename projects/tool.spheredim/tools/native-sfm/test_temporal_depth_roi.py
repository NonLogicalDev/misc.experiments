import unittest
import subprocess
import sys
from pathlib import Path
import cv2
import numpy as np
import temporal_depth_roi as d

class DepthRoiTests(unittest.TestCase):
    def test_duplicate_neighbors_are_rejected_before_inputs_are_read(self):
        script=Path(d.__file__)
        result=subprocess.run([sys.executable,str(script),'missing-prepared','missing-model','missing-output','--reference','1435','--neighbors','1420','1420','1425','--roi','400','330','140','35'],capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('unique neighbors',result.stderr)

    def test_erp_projection_matches_known_bearing_after_camera_translation(self):
        R=np.eye(3);C=np.array([.3,-.2,.1]);point=C+3*d.rays(700,190,1024,512)
        x,y,r=d.project(point,R,C,1024,512)
        np.testing.assert_allclose([x,y,r],[700,190,3],atol=1e-9)

    def test_off_axis_rotated_camera_reprojects_world_bearing(self):
        angle=.37; R=np.array([[np.cos(angle),0,np.sin(angle)],[0,1,0],[-np.sin(angle),0,np.cos(angle)]])
        center=np.array([.7,-.2,.4]);camera_ray=d.rays(703,181,1024,512)
        point=center+4.3*(camera_ray@R)
        x,y,distance=d.project(point,R,center,1024,512)
        np.testing.assert_allclose([x,y,distance],[703,181,4.3],atol=1e-9)

    def test_bilinear_footprint_rejects_masked_neighbor_and_wraps(self):
        img=np.arange(32,dtype=np.float32).reshape(4,8);mask=np.full((4,8),255,np.uint8)
        _,valid=d.sample(img,mask,np.array([7.5,2.5]),np.array([1.,1.]))
        self.assertTrue(valid.all());mask[1,0]=0
        _,valid=d.sample(img,mask,np.array([7.5,2.5]),np.array([1.,1.]))
        np.testing.assert_array_equal(valid,[False,True])

    def test_distinct_supported_peak_accepted(self):
        scores=np.full((3,12),.1);scores[:,5]=[.94,.93,.92]
        r,reason=d.select_depth(scores,np.arange(1,13));self.assertIsNone(reason);self.assertEqual(r['depth'],6);self.assertEqual(r['views'],3)

    def test_known_sphere_depth_with_real_patch_matching_and_mask_rejection(self):
        # The reference camera is at the sphere center: a constant radial-depth
        # patch is exact, while translated cameras see genuine ERP reprojection.
        yy,xx=np.indices((512,1024));directions=d.rays(xx,yy,1024,512)
        def render(center, rotation):
            world_rays=directions@rotation
            dot=np.sum(world_rays*center,axis=-1)
            t=-dot+np.sqrt(dot*dot+9-np.dot(center,center))
            p=center+world_rays*t[...,None]
            return (.5+.18*np.sin(37*p[...,0]+11*p[...,1])+.15*np.cos(29*p[...,1]-7*p[...,0])+.1*np.sin(19*p[...,0]+23*p[...,1])).astype(np.float32)
        origin=np.zeros(3);mask=np.full((512,1024),255,np.uint8);ref=render(origin,np.eye(3))
        centers=[np.array([-.6,0.,0.]),np.array([.6,0.,0.]),np.array([0.,.6,0.])]
        angle=.09; rotation=np.array([[np.cos(angle),0,np.sin(angle)],[0,1,0],[-np.sin(angle),0,np.cos(angle)]])
        rotations=[rotation,np.eye(3),rotation.T]
        target=[(render(c,r),mask.copy(),(r,c)) for c,r in zip(centers,rotations)]
        depths=np.linspace(1.4,4.6,33)
        result,reason=d.match_pixel(ref,mask,(np.eye(3),origin),target,620,220,depths)
        self.assertIsNone(reason);self.assertLess(abs(result['depth']-3),.16);self.assertTrue(result['leave_one_out_checked'])
        # Masking a full target view's interpolation footprint leaves only one
        # matching neighbor, which cannot satisfy the two-view requirement.
        target[0][1][:]=0;target[1][1][:]=0
        self.assertIsNone(d.match_pixel(ref,mask,(np.eye(3),origin),target,620,220,depths)[0])
        # Repeating the same stripes along the searched direction has no unique depth.
        stripe=(.5+.4*np.sin(xx*2*np.pi/8)).astype(np.float32)
        repeated=[(stripe,mask,(np.eye(3),c)) for c in centers]
        self.assertIsNone(d.match_pixel(stripe,mask,(np.eye(3),origin),repeated,620,220,depths)[0])
        flat=np.full_like(ref,.5)
        self.assertEqual(d.match_pixel(flat,mask,(np.eye(3),origin),target,620,220,depths)[1],'reference_mask_or_low_texture')

    def test_unobserved_competitor_cannot_prove_unique_peak(self):
        scores=np.full((3,12),-2.);scores[:,5]=.95
        self.assertIsNone(d.select_depth(scores,np.arange(12))[0])

    def test_repeated_stripes_and_disagreeing_views_rejected(self):
        scores=np.full((3,12),.1);scores[:,4]=.95;scores[:,9]=.94
        self.assertIsNone(d.select_depth(scores,np.arange(12))[0])
        scores=np.full((3,12),.1);scores[0,4]=.95;scores[1,4]=.94;scores[1,9]=.96;scores[2,9]=.95
        self.assertIsNone(d.select_depth(scores,np.arange(12))[0])

if __name__=='__main__':unittest.main()
