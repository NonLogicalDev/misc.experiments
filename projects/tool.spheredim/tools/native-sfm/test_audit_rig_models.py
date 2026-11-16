import sys,unittest,tempfile,struct
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
import audit_rig_models as m
class AuditTests(unittest.TestCase):
 def test_common_observations_and_all_validity(self):
  track=[['a',0,1,1],['b',1,2,2],['c',2,3,3],['d',3,4,4]]
  poses={name:{k:None for k in keys} for name,keys in [('one','abcd'),('two','abcd'),('three','abc'),('four','abcd'),('five','abcd')]};seen=[]
  def score(obs,model,width,height):seen.append([o[0] for o in obs]);return ([1.0],None) if 'd' in model else (None,'negative')
  with patch.object(m.c,'score_track',side_effect=score):common,results,valid=m.common_scores(track,poses,1024,512)
  self.assertEqual([o[0] for o in common],['a','b','c']);self.assertEqual(seen,[['a','b','c']]*5);self.assertFalse(valid);self.assertEqual(results['three'][1],'negative')
 def test_match_payload_vs_telemetry_tail(self):
  with tempfile.TemporaryDirectory() as temp:
   a=Path(temp)/'a';b=Path(temp)/'b';head=b'VKMT'+struct.pack('<II',5,1)+struct.pack('<I',1)+b'x'+struct.pack('<I',3)+struct.pack('<II',0,0)
   a.write_bytes(head+b'\x00');b.write_bytes(head+b'\x01'+struct.pack('<I',1)+bytes(80)+bytes(8));x=m.match_sections(a);y=m.match_sections(b)
   self.assertEqual(x['image_and_match_records_sha256'],y['image_and_match_records_sha256']);self.assertEqual(x['camera_metadata_sha256'],y['camera_metadata_sha256']);self.assertFalse(x['sensor_calibration_sample_present']);self.assertEqual(y['sensor_rotation_pair_samples'],1)
if __name__=='__main__':unittest.main()
