import importlib.util
import math
import tempfile
import unittest
from pathlib import Path

spec=importlib.util.spec_from_file_location('export_sfm_viewer',Path(__file__).resolve().parents[1]/'scripts'/'export_sfm_viewer.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class ViewerPoseTests(unittest.TestCase):
    def test_colmap_inverse_and_split(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'images.txt'; q=math.sqrt(.5)
            p.write_text(f'1 {q} 0 0 {q} 1 2 3 1 frame_000000.png\n\n2 1 0 0 0 0 0 0 1 frame_000015.png\n\n')
            poses=m.read_poses(p); a=poses['frame_000000.png']
            for actual,expected in zip([a[0][0],a[0][1],a[1][0],a[1][1],a[0][3],a[1][3],a[2][3]],[0,1,-1,0,-2,1,-3]): self.assertAlmostEqual(actual,expected)
            f=m.build_frames(poses,{'names':list(poses),'camera_count':2},{'frames':[{'source_frame':0,'video_pts_s':0},{'source_frame':15,'video_pts_s':.5005}]})
            self.assertEqual([(v['source_frame'],v['split']) for v in f],[(0,'heldout'),(15,'train')])
            with self.assertRaises(ValueError): m.build_frames(poses,{'names':['frame_000000.png'],'camera_count':1},{'frames':[]})
    def test_reordered_dataset_uses_source_times_and_original_split(self):
        identity=[[1,0,0,0],[0,1,0,0],[0,0,1,0]]
        names=['000000_frame_000015.png','000001_frame_000000.png']
        dataset={'names':names,'camera_count':2,'frames':[{'name':names[0],'source_name':'frame_000015.png','source_frame':15,'time_seconds':0.5},{'name':names[1],'source_name':'frame_000000.png','source_frame':0,'time_seconds':0.0}]}
        review={'frames':[{'source_frame':0,'video_pts_s':0.0},{'source_frame':15,'video_pts_s':0.5}]}
        frames=m.build_frames(dict.fromkeys(names,identity),dataset,review)
        self.assertEqual([(f['source_frame'],f['split']) for f in frames],[(0,'train'),(15,'heldout')])
        dataset['frames'][0]['source_frame']=14
        with self.assertRaises(ValueError):m.build_frames(dict.fromkeys(names,identity),dataset,review)

    def test_up_from_camera_axes(self):
        frames=[{'world_from_camera': [[1,0,0,0],[0,1,0,0],[0,0,1,0]]} for _ in range(3)]
        up, evidence=m.estimate_up(frames)
        self.assertEqual(up,[0,-1,0])
        self.assertAlmostEqual(evidence['max_degrees'],0)

    def test_reject_invalid_quaternion(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'images.txt';p.write_text('1 2 0 0 0 0 0 0 1 frame_000000.png\n\n')
            with self.assertRaises(ValueError):m.read_poses(p)

if __name__=='__main__':unittest.main()
