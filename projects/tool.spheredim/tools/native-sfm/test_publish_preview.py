import importlib.util
import json
from pathlib import Path
import struct
import tempfile
import unittest
import numpy as np

spec=importlib.util.spec_from_file_location('preview',Path(__file__).with_name('publish_preview.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class PreviewTest(unittest.TestCase):
    def fixture(self,root):
        (root/'progress').mkdir();(root/'sparse/0').mkdir(parents=True);(root/'out').mkdir()
        names=['cam0/frame_000001','cam1/frame_000001','cam0/frame_000002','cam1/frame_000002','cam0/frame_000003','cam1/frame_000003']
        data=b'VKMT'+struct.pack('<II',5,len(names))
        for name in names:
            n=name.encode();data+=struct.pack('<I',len(n))+n+struct.pack('<I',1)
        (root/'matches.bin').write_bytes(data)
        model=b'VKPM'+struct.pack('<IIIIQ',4,0,len(names),len(names),1)
        for i in range(len(names)):
            # OpenGL camera->world: conversion makes a CV identity.
            mat=[1,0,0,float(i//2),0,-1,0,0,0,0,-1,0]
            model+=struct.pack('<I12fIIII2d',i,*mat,1024,512,17,2,1024,512)
        model+=struct.pack('<I3f3B',1,1.,2.,3.,10,20,30)
        (root/'progress/model.bin').write_bytes(model)
        rows=[{'source_frame':i,'timestamp_microseconds':i*1000000} for i in (1,2,3)]
        (root/'dataset.json').write_text(json.dumps({'frames':rows}))
        return model

    def test_snapshot_and_invalid_replacement(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);data=self.fixture(root)
            key=m.publish(root/'progress',root/'sparse/0',root/'dataset.json',root/'out')
            state=json.loads((root/'out/viewer-state.json').read_text()); before=(root/'out/viewer-state.json').read_bytes()
            frames=json.loads((root/'out'/state['trajectory']['poses']).read_text())['frames']
            self.assertEqual(len(frames),3);self.assertEqual([x['source_frame'] for x in frames],[1,2,3])
            np.testing.assert_allclose(np.array(frames[0]['world_from_camera'])[:,:3],np.eye(3))
            self.assertEqual(state['up'],[0.,1.,0.]);self.assertEqual(state['generation'],key)
            self.assertIn('1 2 3 10 20 30',(root/'out'/state['trajectory']['points']).read_text())
            (root/'progress/model.bin').write_bytes(data[:-3])
            with self.assertRaises(ValueError):m.publish(root/'progress',root/'sparse/0',root/'dataset.json',root/'out')
            self.assertEqual((root/'out/viewer-state.json').read_bytes(),before)

    def test_status_counts_and_no_zero_progress(self):
        self.assertEqual(m.status_stage(None),{'name':'Reconstruction','status':'running'})
        base={'stage':5,'flags':1,'done':0,'total':0,'registered':6,'images':6,'points':4,'models':1}
        self.assertEqual(m.status_stage(base),{'name':'Reconstruction','status':'complete','detail':'Reconstruction complete'})
        self.assertIn('6/6',m.coverage_details(base)[0])
        partial={**base,'flags':3}
        self.assertEqual(m.status_stage(partial)['status'],'partial')
        running={**base,'flags':0,'stage':2,'done':2,'total':5}
        self.assertEqual(m.status_stage(running)['current'],2)
        self.assertNotIn('current',m.status_stage({**running,'total':0}))

    def test_finished_prefers_complete_final_and_preserves_partial(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.fixture(root)
            status=lambda flags:struct.pack('<4sIII6qd',b'VKPS',1,5,flags,0,0,6,6,1,1,0.)
            (root/'progress/status.bin').write_bytes(status(1))
            # Until final files are complete, publish the last complete native snapshot.
            m.publish(root/'progress',root/'sparse/0',root/'dataset.json',root/'out')
            before=json.loads((root/'out/viewer-state.json').read_text())
            self.assertIn('native progress',before['details'][0])
            images=struct.pack('<Q',3)
            for i in (1,2,3):
                images+=struct.pack('<i7di',i,1.,0.,0.,0.,float(-i),0.,0.,1)
                images+=f'cam0/frame_{i:06}.png'.encode()+b'\0'+struct.pack('<Q',0)
            (root/'sparse/0/images.bin').write_bytes(images)
            (root/'sparse/0/points3D.bin').write_bytes(struct.pack('<Q',1)+struct.pack('<Q3d3BdQ',1,4.,5.,6.,100,110,120,0.,0))
            m.publish(root/'progress',root/'sparse/0',root/'dataset.json',root/'out')
            after=json.loads((root/'out/viewer-state.json').read_text())
            self.assertIn('final COLMAP',after['details'][0]);self.assertNotEqual(before['generation'],after['generation'])
            self.assertEqual(after['stages'][0]['status'],'complete')
            (root/'progress/status.bin').write_bytes(status(3))
            m.publish(root/'progress',root/'sparse/0',root/'dataset.json',root/'out')
            self.assertEqual(json.loads((root/'out/viewer-state.json').read_text())['stages'][0]['status'],'partial')

    def test_source_switch_clears_previous_geometry_and_uses_new_log(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); a=root/'a';b=root/'b';a.mkdir();b.mkdir()
            self.fixture(a);self.fixture(b)
            out=root/'out';out.mkdir();pointer=root/'active';pointer.symlink_to(a, target_is_directory=True)
            m.publish(pointer/'progress',pointer/'sparse/0',a/'dataset.json',out)
            old=json.loads((out/'viewer-state.json').read_text())
            self.assertTrue(old['trajectory']['poses']);self.assertNotIn('scenes',old)
            (b/'progress/model.bin').unlink()
            (b/'progress/status.bin').write_bytes(struct.pack('<4sIII6qd',b'VKPS',1,2,0,3,6,0,6,0,0,0.))
            pointer.unlink();pointer.symlink_to(b,target_is_directory=True)
            with self.assertRaises(OSError):m.publish(pointer/'progress',pointer/'sparse/0',b/'dataset.json',out)
            pending=json.loads((out/'viewer-state.json').read_text())
            self.assertEqual(pending['source'],str(b.resolve()))
            self.assertEqual(pending['trajectory'],{})
            self.assertEqual(pending['stages'][0]['current'],3)
            self.assertEqual((out/pending['logs'][0]['file']).resolve(),(b/'run.log').resolve())
            self.assertNotIn('currentScene',pending)

    def test_activity_override_updates_without_geometry_change_and_is_run_scoped(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);a=root/'a';b=root/'b';a.mkdir();b.mkdir()
            self.fixture(a);self.fixture(b)
            out=root/'out';out.mkdir();pointer=root/'active';pointer.symlink_to(a,target_is_directory=True)
            activity=pointer/'activity.json'
            activity.write_text(json.dumps({'stages':[{'name':'Checking alignment','status':'running'}],
                                            'currentActivity':0,'logs':[{'name':'Audit','file':'audit.log'}]}))
            key=m.publish(pointer/'progress',pointer/'sparse/0',a/'dataset.json',out,activity_state=activity)
            first=json.loads((out/'viewer-state.json').read_text())
            self.assertEqual(first['stages'][0]['name'],'Checking alignment')
            self.assertNotIn('total',first['stages'][0])
            self.assertEqual((out/first['logs'][1]['file']).resolve(),(a/'audit.log').resolve())
            activity.write_text(json.dumps({'stages':[{'name':'Reconstructing','status':'running'}],'currentActivity':0}))
            self.assertEqual(m.publish(pointer/'progress',pointer/'sparse/0',a/'dataset.json',out,activity_state=activity),key)
            second=json.loads((out/'viewer-state.json').read_text())
            self.assertEqual(second['stages'][0]['name'],'Reconstructing')
            self.assertEqual(first['trajectory'],second['trajectory'])
            (a/'progress/model.bin').write_bytes(b'incomplete')
            activity.write_text(json.dumps({'stages':[{'name':'Inspecting results','status':'running'}],'currentActivity':0}))
            m.refresh_activity(pointer/'progress',pointer/'sparse/0',out,activity)
            third_same=json.loads((out/'viewer-state.json').read_text())
            self.assertEqual(third_same['stages'][0]['name'],'Inspecting results')
            self.assertEqual(third_same['trajectory'],second['trajectory'])
            # An old run's activity file cannot override a newly selected run.
            pointer.unlink();pointer.symlink_to(b,target_is_directory=True)
            m.publish(pointer/'progress',pointer/'sparse/0',b/'dataset.json',out,activity_state=a/'activity.json')
            third=json.loads((out/'viewer-state.json').read_text())
            self.assertEqual(third['stages'][0]['name'],'Reconstruction')
            self.assertEqual(len(third['logs']),1)

    def test_alignment_from_fused(self):
        frames=[{'source_frame':i,'timestamp_microseconds':i*1000000,'fused_row':{'q_w':'1','q_x':'0','q_y':'0','q_z':'0'}} for i in (1,2,3)]
        poses={f'cam0/frame_{i:06}':np.column_stack((m.BODY_FROM_CV,np.array([i,0,0]))) for i in (1,2,3)}
        _,up,method=m.build_frames(poses,{'frames':frames})
        np.testing.assert_allclose(up,[0,0,1],atol=1e-12);self.assertIn('fused',method)

if __name__=='__main__':unittest.main()
