import unittest
import numpy as np
import select_track_coverage as s


class TrackSelectionTests(unittest.TestCase):
    def test_preserves_multiview_and_paired_timestamp(self):
        centers=[np.array([float(i),0.,0.]) for i in range(4)]
        tracks={10:[(i,'cam0',centers[i]) for i in range(4)],11:[(i,'cam1',centers[i]) for i in range(4)]}
        points={10:np.array([0.,0.,5.]),11:np.array([1.,0.,5.])}
        selected,snapshot,_,_,_=s.prune(range(4),tracks,points,{0:0,1:1,2:1,3:1},min_shared=1,cap=3)
        self.assertGreaterEqual(len(selected),3);self.assertEqual(len(snapshot),3)
        self.assertTrue(set(selected)<=set(range(4)))
        for p,obs in tracks.items():
            self.assertGreaterEqual(len({x[0] for x in obs}&set(selected)),3)

    def test_exact_three_view_track_cannot_be_reduced_to_two(self):
        centers=[np.array([float(i),0.,0.]) for i in range(3)]
        tracks={1:[(i,'cam0',centers[i]) for i in range(3)]}
        selected,snapshot,blocked,_,pinned=s.prune(range(3),tracks,{1:np.array([0.,0.,5.])},{0:0,1:0,2:0},min_shared=1,cap=2)
        self.assertEqual(selected,[0,1,2]);self.assertIsNone(snapshot)
        self.assertEqual(pinned,3);self.assertGreater(blocked['landmark_support'],0)

    def test_patch_detail_rejects_boundary_and_uniform_input(self):
        image=np.tile(np.where(np.arange(64)%8<4,40,180).astype(np.uint8),(64,1))
        mask=np.ones_like(image,bool);mask[:,40:]=False
        detail,valid=s.patch_detail(image,mask)
        self.assertGreater(float(detail[30,20]),0)
        self.assertFalse(valid[30,40]);self.assertFalse(valid[30,38])
        with self.assertRaisesRegex(ValueError,'valid source'):
            s.patch_detail(image,np.zeros_like(mask))

    def test_prevents_removing_only_bridge(self):
        centers=[np.array([float(i),0.,0.]) for i in range(3)]
        tracks={1:[(0,'cam0',centers[0]),(1,'cam0',centers[1])],2:[(1,'cam0',centers[1]),(2,'cam0',centers[2])]}
        selected,_,_,_,_=s.prune(range(3),tracks,{1:np.array([0.,0.,5.]),2:np.array([1.,0.,5.])},{0:10,1:0,2:10},min_shared=1)
        self.assertIn(1,selected)


if __name__=='__main__':unittest.main()
