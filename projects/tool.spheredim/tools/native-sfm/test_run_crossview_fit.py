import tempfile
import unittest
from pathlib import Path
import cv2
import numpy as np
import run_crossview_fit as run

class ReferenceDedupTests(unittest.TestCase):
 def test_only_exact_pixels_are_hardlinked(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);out=root/'zero';out.mkdir();(root/'data/images').mkdir(parents=True);(root/'data/masks').mkdir();image=np.full((8,8,3),42,np.uint8);mask=np.full((8,8),255,np.uint8)
   cv2.imwrite(str(root/'data/images/eval.png'),image);cv2.imwrite(str(root/'data/masks/eval.png'),mask);cv2.imwrite(str(out/'eval-gt-00000.png'),image);cv2.imwrite(str(out/'eval-mask-00000.png'),mask)
   evidence=run.deduplicate_references(root,out,['eval.png']);self.assertEqual(len(evidence),2);self.assertEqual((out/'eval-gt-00000.png').stat().st_ino,(root/'data/images/eval.png').stat().st_ino)
 def test_changed_pixel_rejected(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);out=root/'zero';out.mkdir();(root/'data/images').mkdir(parents=True);(root/'data/masks').mkdir();image=np.full((8,8,3),42,np.uint8);cv2.imwrite(str(root/'data/images/eval.png'),image);image[0,0]=0;cv2.imwrite(str(out/'eval-gt-00000.png'),image)
   with self.assertRaisesRegex(ValueError,'differs'):run.deduplicate_references(root,out,['eval.png'])
if __name__=='__main__':unittest.main()
