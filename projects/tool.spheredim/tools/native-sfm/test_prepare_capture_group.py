import importlib.util,json,tempfile,unittest
from pathlib import Path
s=importlib.util.spec_from_file_location('group',Path(__file__).with_name('prepare_capture_group.py'));mod=importlib.util.module_from_spec(s);s.loader.exec_module(mod)
class TestGroup(unittest.TestCase):
 def test_exact_pose_split_and_hardlinks(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t);d=p/'data';(d/'images').mkdir(parents=True);(d/'masks').mkdir();(d/'sparse/0').mkdir(parents=True)
   for n in ['train_a.png','train_b.png','eval_c.png']:
    (d/'images'/n).write_bytes(n.encode());(d/'masks'/n).write_bytes(b'mask')
   (d/'seed.ply').write_bytes(b'seed');(d/'sparse/0/cameras.txt').write_text('camera\n');(d/'sparse/0/images.txt').write_text('1 1 0 0 0 1 2 3 1 train_a.png\n\n2 1 0 0 0 4 5 6 1 train_b.png\n\n3 1 0 0 0 7 8 9 1 eval_c.png\n\n');m={'seed_sha256':mod.sha(d/'seed.ply'),'frames':[{'name':n,'split':'eval' if n.startswith('eval') else 'train'} for n in ['train_a.png','train_b.png','eval_c.png']]};(d/'manifest.json').write_text(json.dumps(m));out=p/'out';mod.prepare(d/'manifest.json',out,['train_a.png'],['train_b.png','eval_c.png']);rows=(out/'data/sparse/0/images.txt').read_text();self.assertIn('2 1 0 0 0 4 5 6 1 eval_b.png',rows);self.assertEqual((out/'data/images/eval_b.png').stat().st_ino,(d/'images/train_b.png').stat().st_ino);self.assertFalse((out/'INCOMPLETE').exists())
   with self.assertRaises(ValueError):mod.prepare(d/'manifest.json',p/'bad',['train_a.png'],['train_a.png'])
   with self.assertRaises(ValueError):mod.prepare(d/'manifest.json',p/'bad',['eval_c.png'],['train_b.png'])
if __name__=='__main__':unittest.main()
