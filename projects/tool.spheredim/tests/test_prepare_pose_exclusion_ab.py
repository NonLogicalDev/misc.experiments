import importlib.util,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('ab',Path(__file__).resolve().parents[1]/'scripts'/'prepare_pose_exclusion_ab.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class SplitTests(unittest.TestCase):
 def test_preserves_holdouts_with_reordered_indices(self):
  names=[f'frame_{i:06}.png' for i in range(133)];bad=(names[1],names[2],names[3]);new=m.reorder(names,bad)
  self.assertEqual(len(new),130);self.assertEqual(new[::8],names[::8]);self.assertEqual(set(new),set(names)-set(bad));self.assertEqual(len(set(new)),130)
 def test_rejects_holdout_duplicate_and_missing(self):
  names=[f'frame_{i:06}.png' for i in range(133)]
  for bad in ((names[0],),('missing',),(names[1],names[1])):
   with self.assertRaises(ValueError):m.reorder(names,bad)
if __name__=='__main__':unittest.main()
