import time
import unittest
import numpy as np
import temporal_depth_roi as erp
import refine_photometric_plane as fit

class PlaneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        h, w = fit.H, fit.W
        y, x = np.indices((h,w))
        cls.normal = np.array([0.,0.,1.])
        cls.d = -3.
        cls.ref_pose = (np.eye(3), np.zeros(3))
        angle = .025
        rotation = np.array([[np.cos(angle), 0, np.sin(angle)], [0, 1, 0], [-np.sin(angle), 0, np.cos(angle)]])
        cls.poses = [(rotation, np.array([dx,dy,0.])) for dx,dy in [(.6,0),(-.5,.25),(.4,-.35)]]
        def image(pose):
            R,C=pose
            ray=erp.rays(x.ravel()+.5,y.ravel()+.5,w,h)@R
            distance=(3-C[2])/np.where(abs(ray[:,2])>1e-6,ray[:,2],np.nan)
            P=C+ray*distance[:,None]
            value=125+40*np.sin(P[:,0]*6)+35*np.cos(P[:,1]*7)+20*np.sin(P[:,0]*3+P[:,1]*4)
            value=np.nan_to_num(value,nan=0)
            return np.repeat(np.clip(value,0,255).astype(np.uint8).reshape(h,w,1),3,axis=2)
        cls.ref=image(cls.ref_pose)
        cls.mask=np.full((h,w),255,np.uint8)
        cls.targets=[(image(p),cls.mask,p) for p in cls.poses]
        # ERP rays close to +z, spread in two dimensions.
        offsets=np.array([(a,b) for a in range(-3,4) for b in range(-3,4)])
        cls.xy=np.concatenate([offsets + [x,y] for x in (900,960,1024,1080,1140) for y in (430,480,540,590)])
        cls.source=cls.ref[cls.xy[:,1],cls.xy[:,0]].astype(float)
    def test_true_plane_beats_wrong_offset(self):
        good, ok=fit.samples([0,0,0],self.normal,self.d,3,self.xy,self.ref_pose,self.poses[0],self.targets[0][0],self.mask)
        wrong, ok2=fit.samples([0,0,.05],self.normal,self.d,3,self.xy,self.ref_pose,self.poses[0],self.targets[0][0],self.mask)
        self.assertTrue(ok and ok2)
        self.assertLess(np.mean((good-self.source)**2),np.mean((wrong-self.source)**2))
    def test_optimization_recovers_depth_with_rotated_cameras(self):
        best, _, _, singular = fit.fit_plane(self.source, self.xy, self.ref_pose, self.targets, self.normal, -3.06, 3., time.monotonic()+40)
        self.assertAlmostEqual(best['x'][2], .02, delta=.008)
        self.assertIsNotNone(singular)
    def test_degenerate_and_failed_fit_are_unresolved(self):
        self.assertEqual(fit.classify({'success': True}, [2., 1., 0.], [False]*3, [], True)[0], 'unresolved')
        self.assertEqual(fit.classify({'success': False}, [2., 1., .5], [False]*3, [], True)[0], 'unresolved')
        self.assertEqual(fit.classify({'success': True}, [2., 1., .5], [False]*3, [], False)[0], 'unresolved')
    def test_invalid_mask_rejects_entire_candidate(self):
        mask=np.zeros_like(self.mask)
        _, ok=fit.samples([0,0,0],self.normal,self.d,3,self.xy,self.ref_pose,self.poses[0],self.targets[0][0],mask)
        self.assertFalse(ok)
    def test_zero_baseline_has_no_depth_information(self):
        a,ok=fit.samples([0,0,0],self.normal,self.d,3,self.xy,self.ref_pose,self.ref_pose,self.ref,self.mask)
        b,ok2=fit.samples([0,0,.04],self.normal,self.d,3,self.xy,self.ref_pose,self.ref_pose,self.ref,self.mask)
        self.assertTrue(ok and ok2)
        np.testing.assert_allclose(a,b,atol=1e-8)

if __name__ == '__main__': unittest.main()
