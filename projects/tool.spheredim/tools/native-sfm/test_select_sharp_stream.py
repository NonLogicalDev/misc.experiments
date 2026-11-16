import csv, json, tempfile, types, unittest
from pathlib import Path
from unittest.mock import patch
import select_sharp_stream as s

class PlanTests(unittest.TestCase):
 def test_windows_preserve_anchor_and_provenance(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);source=p/'recording';source.write_bytes(b'video');native=p/'native';native.write_bytes(b'native');(p/'masks').mkdir();(p/'masks'/'a.png').write_bytes(b'a');(p/'masks'/'b.png').write_bytes(b'b')
   review=p/'review.json';review.write_text(json.dumps({'frame_dimensions':[1024,512],'frames':[{'source_frame':0,'video_pts_s':'0','mask':'a.png'},{'source_frame':12,'video_pts_s':'0.12','mask':'b.png'}]}));fused=p/'fused.csv'
   with fused.open('w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=['frame','video_pts_s']);w.writeheader();w.writerows({'frame':i,'video_pts_s':str(i/100)} for i in range(13))
   with patch.object(s.dense,'packet_map',return_value=([],[])),patch.object(s.sharp,'pair_pts',side_effect=lambda us,a,b:[{'pts':us},{'pts':us}]),patch.object(s.importlib.util,'find_spec',return_value=types.SimpleNamespace(origin=str(native))):
    plan=s.prepare(source,review,fused,[5,10],2)
   self.assertEqual([len(x['candidates']) for x in plan['results']],[5,5]);self.assertTrue(all(x['requested_frame'] in [c['frame'] for c in x['candidates']] for x in plan['results']));self.assertEqual(len(plan['review_mask_sha256']),2);self.assertEqual(plan['results'][0]['candidates'][0]['timestamp_microseconds'],30000)
 def test_mask_range_clips_at_both_endpoints(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);source=p/'recording';source.write_bytes(b'video');native=p/'native';native.write_bytes(b'native');(p/'masks').mkdir();(p/'masks'/'a').write_bytes(b'a');(p/'masks'/'b').write_bytes(b'b')
   review=p/'review';review.write_text(json.dumps({'frame_dimensions':[1024,512],'frames':[{'source_frame':2,'video_pts_s':'0.02','mask':'a'},{'source_frame':10,'video_pts_s':'0.10','mask':'b'}]}));fused=p/'fused'
   with fused.open('w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=['frame','video_pts_s']);w.writeheader();w.writerows({'frame':i,'video_pts_s':str(i/100)} for i in range(13))
   with patch.object(s.dense,'packet_map',return_value=([],[])),patch.object(s.sharp,'pair_pts',return_value=[{},{}]),patch.object(s.importlib.util,'find_spec',return_value=types.SimpleNamespace(origin=str(native))):plan=s.prepare(source,review,fused,[2,10],2)
   self.assertEqual([[c['frame'] for c in g['candidates']] for g in plan['results']],[[2,3,4],[8,9,10]])
if __name__=='__main__':unittest.main()
