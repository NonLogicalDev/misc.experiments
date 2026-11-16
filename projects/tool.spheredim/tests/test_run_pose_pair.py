import importlib.util,tempfile,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('runner',Path(__file__).resolve().parents[1]/'scripts'/'run_pose_pair.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class DiskTests(unittest.TestCase):
 def test_counts_outputs_without_following_input_symlinks(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);output=root/'output';output.mkdir();(output/'small').write_bytes(b'123');(root/'source').write_bytes(b'12345678');(output/'link').symlink_to(root/'source')
   self.assertEqual(m.tree_size(output),3);self.assertEqual(m.tree_size(root/'absent'),0)
if __name__=='__main__':unittest.main()
