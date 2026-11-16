import importlib.util
import unittest
import struct
import tempfile
from pathlib import Path
import numpy as np
import cv2

spec = importlib.util.spec_from_file_location('compare_rigs', Path(__file__).with_name('compare_rigs.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class CompareRigsTests(unittest.TestCase):
    def test_correct_origins_beat_collocated(self):
        W,H=1024,512
        point=np.array([.4,.2,5.])
        poses={}; wrong={}; track=[]
        for frame in range(4):
            for camera in range(2):
                name=f'cam{camera}/{frame:06}.png'
                center=np.array([frame*.3+camera*.2,0.,0.])
                poses[name]=(np.eye(3),center)
                wrong[name]=(np.eye(3),np.array([frame*.3,0.,0.]))
                d=point-center
                x=(np.arctan2(d[0],d[2])/(2*np.pi)+.5)*W
                y=(.5-np.arctan2(-d[1],np.hypot(d[0],d[2]))/np.pi)*H
                track.append((name,frame,x,y))
        correct, err=m.score_track(track,poses,W,H)
        bad, baderr=m.score_track(track,wrong,W,H)
        self.assertIsNone(err); self.assertIsNone(baderr)
        self.assertLess(max(correct),1e-4)
        self.assertGreater(np.median(bad),1.)
        result=m.compare([track],poses,wrong,W,H)
        self.assertEqual(result[0]['shared_valid']['count'],len(track)-2)
        self.assertAlmostEqual(result[0]['rig']['baseline_min'],.2)

    def test_binary_poses_and_truncation(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'images.bin'
            row=struct.pack('<i7di',7,1.,0.,0.,0.,-1.,0.,0.,2)
            path.write_bytes(struct.pack('<Q',1)+row+b'cam0/a.png\0'+struct.pack('<Q',1)+struct.pack('<ddq',2.,3.,-1))
            poses=m.read_poses(Path(td))
            np.testing.assert_allclose(poses['cam0/a.png'][1],[1.,0.,0.])
            path.write_bytes(path.read_bytes()[:-1])
            with self.assertRaises(ValueError): m.read_poses(Path(td))

    def test_reject_overlapping_feature_and_evaluation_masks(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            for kind in ('images','eval','feature'):
                for cam in ('cam0','cam1'):
                    directory=root/kind/cam
                    directory.mkdir(parents=True)
                    cv2.imwrite(str(directory/'f.png'),np.full((32,64),255,dtype=np.uint8))
            with self.assertRaisesRegex(ValueError, 'overlap'):
                m.tracks_from_images(root/'images',root/'eval',root/'feature',1)

    def test_spherical_essential_rejects_outliers(self):
        rng=np.random.default_rng(77)
        points=rng.normal(size=(120,3))*3
        points+=np.array([0.,0.,.3])
        angle=.45
        R=np.array([[np.cos(angle),0,np.sin(angle)],[0,1,0],[-np.sin(angle),0,np.cos(angle)]])
        a=points/np.linalg.norm(points,axis=1)[:,None]
        b=(points-np.array([.8,.2,.1]))@R.T
        b/=np.linalg.norm(b,axis=1)[:,None]
        b[-25:]=rng.normal(size=(25,3));b[-25:]/=np.linalg.norm(b[-25:],axis=1)[:,None]
        mask=m.essential_inliers(a,b,threshold=.003)
        self.assertGreaterEqual(mask[:95].sum(),90)
        self.assertLessEqual(mask[95:].sum(),2)
        np.testing.assert_array_equal(mask,m.essential_inliers(a,b,threshold=.003))

    def test_essential_refit_does_not_discard_better_consensus(self):
        rng=np.random.default_rng(6)
        points=rng.normal(size=(80,3))*3
        a=points/np.linalg.norm(points,axis=1)[:,None]
        b=points-np.array([.8,.2,.1]);b/=np.linalg.norm(b,axis=1)[:,None]
        b+=rng.normal(size=b.shape)*.004;b/=np.linalg.norm(b,axis=1)[:,None]
        b[-15:]=rng.normal(size=(15,3));b[-15:]/=np.linalg.norm(b[-15:],axis=1)[:,None]
        self.assertEqual(m.essential_inliers(a,b,threshold=.008,trials=64).sum(),65)

    def test_spherical_essential_rejects_degenerate_and_small_input(self):
        same=np.tile([0.,0.,1.],(20,1))
        self.assertEqual(m.essential_inliers(same,same).sum(),0)
        self.assertEqual(m.essential_inliers(same[:11],same[:11]).sum(),0)

    def test_degenerate_rays(self):
        d=np.array([0.,0.,1.]); c=np.zeros(3)
        self.assertEqual(m.triangulate((c,d),(c,d))[1],'degenerate')

if __name__=='__main__': unittest.main()
