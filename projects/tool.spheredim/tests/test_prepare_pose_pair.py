import importlib.util,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('pair',Path(__file__).resolve().parents[1]/'scripts'/'prepare_pose_pair.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class PairTests(unittest.TestCase):
 def test_bad_holdout_fails(self):
  b={'names':[f'frame_{i:06}.png' for i in range(133)]}; e={'frames':[{'name':str(i),'source_name':b['names'][i],'split':'heldout' if i%8==0 else 'train'} for i in range(130)]}
  with self.assertRaises(ValueError):m.validate_pair(b,e)
if __name__=='__main__':unittest.main()
