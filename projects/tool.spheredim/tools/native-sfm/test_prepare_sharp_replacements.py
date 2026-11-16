import unittest, tempfile, json
from pathlib import Path
import numpy as np
import prepare_sharp_replacements as s

class ConversionTests(unittest.TestCase):
 def test_area_support_and_operator_keep(self):
  image=np.zeros((1024,2048,3),np.uint8);image[:2,:2]=[[[0,0,0],[4,8,12]],[[8,16,24],[12,24,36]]];support=np.full((1024,2048),255,np.uint8);operator=np.full((512,1024),255,np.uint8)
  support[0,2]=0;operator[0,2]=0
  rgb,native,op,keep,guard=s.process(image,support,operator)
  self.assertEqual(rgb[0,0].tolist(),[6,12,18]);self.assertFalse(native[0,1]);self.assertFalse(op[0,2]);self.assertFalse(keep[0,1]);self.assertFalse(keep[0,2]);self.assertEqual(rgb[0,1].tolist(),[0,0,0]);self.assertFalse(guard[0,0])
 def test_mask_provenance_mismatch(self):
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'report';path.write_bytes(b'selection');masks={'source_report_sha256':s.sha(path),'frames':[{'frame':12,'anchor':10,'mask_brackets':[0,15]}]};selection={'results':[{'requested_frame':10,'selected_frame':12,'candidates':[{'frame':12,'mask_brackets':[0,15]}]}]};s.validate_mask_source(masks,selection,path)
   masks['frames'][0]['mask_brackets']=[0,30]
   with self.assertRaisesRegex(ValueError,'brackets differ'):s.validate_mask_source(masks,selection,path)
   masks['source_report_sha256']='bad'
   with self.assertRaisesRegex(ValueError,'report hash differs'):s.validate_mask_source(masks,selection,path)
 def test_missing_unchanged_control_rejected_before_outputs(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);baseline=p/'baseline';baseline.mkdir();(baseline/'manifest.json').write_text(json.dumps({'frames':[]}));selection=p/'selection.json';selection.write_text(json.dumps({'source_sha256':'source','results':[{'requested_frame':40,'selected_frame':42,'candidates':[{'frame':42,'mask_brackets':[30,45]}]}]}));masks=p/'masks.json';masks.write_text(json.dumps({'source_report_sha256':s.sha(selection),'frames':[{'frame':42,'anchor':40,'mask_brackets':[30,45]}]}));native=p/'native.json';native.write_text(json.dumps({'source_sha256':'source','width':2048,'height':1024,'frames':[{'frame':42}]}));out=p/'output'
   with self.assertRaisesRegex(ValueError,'Missing unchanged'):s.prepare(native,masks,selection,baseline,out)
   self.assertFalse(out.exists())
 def test_invalid_mask_rejected(self):
  image=np.zeros((1024,2048,3),np.uint8);support=np.full((1024,2048),255,np.uint8);operator=np.full((512,1024),255,np.uint8);support[0,0]=2
  with self.assertRaisesRegex(ValueError,'binary'):s.process(image,support,operator)
if __name__=='__main__':unittest.main()
