import tempfile,unittest,json
import cv2
from pathlib import Path
import numpy as np
import evaluate_splat as e

class EvaluateTests(unittest.TestCase):
 def test_mapping_exact_order_and_inventory(self):
  rows=[{'name':'eval_000000_cam0.png','split':'eval'},{'name':'eval_000000_cam1.png','split':'eval'},{'name':'train_000015_cam0.png','split':'train'}];m={'frames':rows,'heldout_evaluation_order':[x['name'] for x in rows[:2]]}
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)
   for kind in ('gt','render','mask'):
    for i in range(2):(p/f'eval-{kind}-{i:05}.png').touch()
   self.assertEqual([x[1]['name'] for x in e.mapping(m,p)],m['heldout_evaluation_order'])
   (p/'eval-gt-00002.png').touch()
   with self.assertRaises(ValueError):e.mapping(m,p)
   (p/'eval-gt-00002.png').unlink();m['heldout_evaluation_order'].reverse()
   with self.assertRaises(ValueError):e.mapping(m,p)
 def test_comparison_requires_identical_inputs(self):
  row={'index':0,'name':'a','source_name':'cam0/a','source_frame':0,'lens':'cam0','timestamp_microseconds':0,'input_sha256':'a','gt_sha256':'b','mask_sha256':'c','spherical':{'weighted_psnr_db':20.},'spherical_ssim':.7};old={'frames':[row],'summary':{'mean_spherical_psnr_db':20.,'mean_spherical_ssim':.7,'mean_gradient_ratio':.5}};new={'frames':[dict(row)],'summary':dict(old['summary'])}
  self.assertEqual(e.compare_reports(old,new,'3k','10k')['mean_spherical_psnr_delta_db'],0)
  new['frames'][0]['mask_sha256']='different'
  with self.assertRaises(ValueError):e.compare_reports(old,new,'3k','10k')
 def test_comparison_labels_preserved_by_evaluation(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);(p/'images').mkdir();(p/'masks').mkdir();run=p/'run';run.mkdir();name='eval_000000_cam0.png';image=np.broadcast_to(np.arange(1024,dtype=np.uint16)[None,:,None]%254+1,(512,1024,3)).astype(np.uint8).copy();mask=np.full((512,1024),255,np.uint8)
   for path,data in ((p/'images'/name,image),(p/'masks'/name,mask),(run/'eval-gt-00000.png',image),(run/'eval-render-00000.png',image-1),(run/'eval-mask-00000.png',mask)):self.assertTrue(cv2.imwrite(str(path),data))
   row={'name':name,'split':'eval','source_name':'cam0/frame_000000.png','source_frame':0,'lens':'cam0','timestamp_microseconds':0};manifest=p/'manifest.json';manifest.write_text(json.dumps({'frames':[row],'heldout_evaluation_order':[name]}))
   e.evaluate(manifest,run,p/'baseline.json',p/'baseline.png');cv2.imwrite(str(run/'eval-render-00000.png'),image);result=e.evaluate(manifest,run,p/'new.json',p/'new.png',compare_to=p/'baseline.json',label='10k',baseline_label='3k');self.assertEqual(result['comparison']['current_label'],'10k');self.assertEqual(result['comparison']['baseline_label'],'3k');self.assertIsNone(result['summary']['mean_spherical_psnr_db']);self.assertIsNone(result['comparison']['per_frame'][0]['spherical_psnr_delta_db'])
 def test_ssim_identity(self):
  image=np.full((32,64,3),128,np.uint8);mask=np.full((32,64),255,np.uint8);self.assertAlmostEqual(e.spherical_ssim(image,image,mask),1.)
if __name__=='__main__':unittest.main()
