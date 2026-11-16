import json,tempfile,unittest
from pathlib import Path
import prepare_one_view_diagnostic as d

class PreparationTests(unittest.TestCase):
 def test_target_source_pose_reference_and_frozen_plan(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp).resolve();source=p/'source';(source/'images').mkdir(parents=True);(source/'masks').mkdir();(source/'sparse/0').mkdir(parents=True);audit=p/'audit';(audit/'render').mkdir(parents=True);target='train_001500_cam0.png';img=source/'images'/target;mask=source/'masks'/target;img.write_bytes(b'image');mask.write_bytes(b'mask');(source/'seed.ply').write_bytes(b'seed');(source/'sparse/0/cameras.txt').write_text('camera');(source/'sparse/0/images.txt').write_text(f'7 1 0 0 0 0 0 0 1 {target}\n\n');ref=audit/'render/eval-render-00000.png';ref.write_bytes(b'render');ply=p/'splat.ply';ply.write_bytes(b'ply');binary=p/'trainer';binary.write_bytes(b'trainer')
   cmd=[str(binary),'train','360-camera','--data',str(source),'--output-dir-prefix',str(p),'--output-dir-name','run','--num-iterations','6000','--steps-per-save','1000','--save-full-checkpoint','1'];base={'frames':[{'name':target,'split':'train'}],'seed_sha256':d.sha(source/'seed.ply'),'binary_sha256':d.sha(binary),'command':cmd};manifest=source/'manifest.json';manifest.write_text(json.dumps(base));a={'checkpoint_ply_sha256':d.sha(ply),'frames':[{'name':target,'source_sha256':d.sha(img),'mask_sha256':d.sha(mask),'render_sha256':d.sha(ref),'index':0,'colmap_pose_row':['7','1','0','0','0','0','0','0','1']}]};am=audit/'audit.json';am.write_text(json.dumps(a));out=p/'diagnostic';plan=d.prepare(manifest,am,ply,out,target)
   self.assertEqual((out/'data/images'/target).stat().st_ino,(out/'data/images/eval_001500_cam0.png').stat().st_ino);self.assertEqual(plan['zero_command'][plan['zero_command'].index('--num-iterations')+1],'0');self.assertEqual(plan['fit_command'][plan['fit_command'].index('--num-iterations')+1],'500');self.assertEqual(plan['fit_command'][plan['fit_command'].index('--max-screen-size')+1],'inf');self.assertEqual(plan['fit_command'][plan['fit_command'].index('--means-lr')+1],'0')
   img.write_bytes(b'changed')
   with self.assertRaisesRegex(ValueError,'Audit source'):d.prepare(manifest,am,ply,p/'bad',target)
if __name__=='__main__':unittest.main()
