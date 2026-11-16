import unittest
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from fractions import Fraction
import cv2
import numpy as np
import select_sharp_frames as s


class SelectionTests(unittest.TestCase):
    def test_windows_do_not_overlap_and_winner_ties_are_deterministic(self):
        groups=s.windows([10, 15, 20], 4, set(range(30)))
        self.assertTrue(all(max(a)<min(b) for a,b in zip(groups,groups[1:])))
        def item(n,score): return {'frame':n,'lenses':[{'score':score},{'score':score}]}
        self.assertEqual(s.select(10,[item(8,1),item(12,1),item(10,1)])['frame'],10)
        self.assertEqual(s.select(10,[item(8,1),item(12,1)])['frame'],8)

    def test_smoothed_texture_beats_blur_and_noise_does_not_dominate(self):
        rng=np.random.default_rng(42)
        base=np.zeros((256,512),np.uint8)
        for y in range(0,256,16):
            for x in range(0,512,16): base[y:y+8,x:x+8]=180
        noisy=np.clip(base.astype(float)+rng.normal(0,18,base.shape),0,255).astype(np.uint8)
        blurred=cv2.GaussianBlur(base,(0,0),3)
        mask=np.ones_like(base,bool)
        scores=s.score_window([noisy,blurred],[mask,mask],0)
        self.assertGreater(scores[0]['score'],scores[1]['score'])
        noise=np.clip(100+rng.normal(0,18,base.shape),0,255).astype(np.uint8)
        with self.assertRaisesRegex(ValueError,'textured'):
            s.score_window([noise],[mask],0)

    def test_weak_texture_is_not_dropped_when_blurred(self):
        yy,xx=np.indices((256,512))
        pattern=np.where((xx//8+yy//8)%2,1,-1)
        amplitudes=np.where(xx<256,70,20)
        src=(128+pattern*amplitudes).astype(np.uint8)
        blurred=cv2.GaussianBlur(src,(0,0),3)
        mask=np.ones_like(src,bool)
        sharp,soft=s.score_window([src,blurred],[mask,mask],0)
        self.assertEqual(sharp['textured_tiles'],soft['textured_tiles'])
        self.assertGreater(sharp['score'],soft['score'])

    def test_blurred_target_can_select_sharper_neighbor(self):
        yy,xx=np.indices((256,512)); sharp=np.where((xx//8+yy//8)%2,30,220).astype(np.uint8)
        blurred=cv2.GaussianBlur(sharp,(0,0),5); mask=np.ones_like(sharp,bool)
        scores=s.score_window([blurred,sharp],[mask,mask],0)
        self.assertGreater(scores[1]['score'],scores[0]['score'])

    def test_partial_mask_pixels_never_become_valid(self):
        image=np.tile(np.where(np.arange(128)%8<4,60,190).astype(np.uint8),(128,1))
        mask=np.ones_like(image,bool);mask[30,30]=False
        _,valid=s.tile_energies(image,mask)
        self.assertFalse(valid[15,15])

    def test_excluded_distractor_cannot_affect_score(self):
        rng=np.random.default_rng(2)
        img=np.tile(np.where(np.arange(512)%16<8,40,180).astype(np.uint8),(256,1))
        modified=img.copy();modified[:,256:]=rng.integers(0,256,(256,256),dtype=np.uint8)
        mask=np.ones_like(img,bool);mask[:,256:]=False
        scores=s.score_window([img,modified],[mask,mask],0)
        self.assertAlmostEqual(scores[0]['score'],scores[1]['score'])

    def test_entrypoint_records_selected_pair_and_removes_temporary_export(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); source=root/'source';source.write_bytes(b'source')
            (root/'masks').mkdir()
            keep=np.full((512,1024),255,np.uint8)
            cv2.imwrite(str(root/'masks/a.png'),keep)
            review=root/'review.json';review.write_text(json.dumps({'frame_dimensions':[1024,512],'frames':[{'source_frame':1,'video_pts_s':1.0,'mask':'a.png'}]}))
            fused=root/'fused.csv';fused.write_text('frame,video_pts_s,q_x,q_y,q_z,q_w,heading_rad\n1,1.000000,0,0,0,1,0\n')
            native=root/'native.so';native.write_bytes(b'native')
            class FakeProcess:
                returncode=0
                def __init__(self,cmd,**kwargs):
                    dest=Path(cmd[cmd.index('--output')+1]); dest.mkdir()
                    image=np.tile(np.where(np.arange(1024)%16<8,40,180).astype(np.uint8),(512,1))
                    frame={'frame':1,'timestamp_microseconds':1000000}
                    for k in ('lens0','lens1','mask0','mask1'):
                        path=dest/(k+'.png'); cv2.imwrite(str(path),keep if k.startswith('mask') else image)
                        frame[k]=str(path); frame[k+'_sha256']=s.rig.sha(path)
                    (dest/'manifest.json').write_text(json.dumps({'frames':[frame]}))
                def poll(self): return 0
            streams={0:Fraction(1,1000),1:Fraction(1,1000)}
            with patch.object(s.dense,'packet_map',return_value=(streams,{0:[1000],1:[1000]})), patch.object(s.subprocess,'Popen',FakeProcess), patch.object(s.importlib.util,'find_spec',return_value=SimpleNamespace(origin=str(native))):
                report=s.run(source,review,fused,root/'out',[1],0,10)
            self.assertEqual(report['results'][0]['selected_frame'],1)
            self.assertEqual(report['results'][0]['candidates'][0]['source_packet_pts'][0]['pts'],1000)
            self.assertEqual({x.name for x in (root/'out').iterdir()},{'selection.json','evidence.png'})

    def test_rejects_missing_or_unequal_pair(self):
        streams={0:Fraction(1,1000),1:Fraction(1,1000)}
        with self.assertRaisesRegex(ValueError,'uniquely matched'):
            s.pair_pts(1000000,streams,{0:[1000],1:[]})
        with self.assertRaisesRegex(ValueError,'unsynchronized'):
            s.pair_pts(1000000,{0:Fraction(1,10000000),1:Fraction(1,10000000)},{0:[10000000],1:[10000001]})


if __name__=='__main__': unittest.main()
