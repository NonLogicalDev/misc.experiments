import tempfile
import unittest
from pathlib import Path
import cv2
import numpy as np
import prepare_dense_splat as d

class OverrideTests(unittest.TestCase):
    def test_override_excludes_only_and_checks_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);base=root/'base';candidate=root/'candidate';name='frame_002020.png'
            for p in (base/'images/cam0',base/'masks/cam0',candidate/'masks/cam0',candidate/'overlays'):p.mkdir(parents=True)
            original=np.full((512,1024),255,np.uint8);original[0,0]=0;new=original.copy();new[100:110,100:110]=0
            cv2.imwrite(str(base/'images/cam0'/name),np.zeros((512,1024,3),np.uint8));cv2.imwrite(str(base/'masks/cam0'/name),original);cv2.imwrite(str(candidate/'masks/cam0'/name),new);cv2.imwrite(str(candidate/'overlays'/name),new)
            e={'frame':2020,'lens':'cam0','source_image_sha256':d.prep.digest(base/'images/cam0'/name),'source_mask_sha256':d.prep.digest(base/'masks/cam0'/name),'override_mask_sha256':d.prep.digest(candidate/'masks/cam0'/name),'overlay_sha256':d.prep.digest(candidate/'overlays'/name),'newly_excluded_pixels':100}
            d.validate_override(base,candidate,2020,'cam0',e)
            new[0,0]=255;cv2.imwrite(str(candidate/'masks/cam0'/name),new);e['override_mask_sha256']=d.prep.digest(candidate/'masks/cam0'/name)
            with self.assertRaisesRegex(ValueError,'binary subset'):d.validate_override(base,candidate,2020,'cam0',e)
            e['source_image_sha256']='wrong'
            with self.assertRaisesRegex(ValueError,'provenance'):d.validate_override(base,candidate,2020,'cam0',e)

if __name__=='__main__':unittest.main()
