import sys
import unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from check_path_sample_quality import check_pair

class PairTests(unittest.TestCase):
    def test_unmasked_pixels_must_match_and_both_arms_share_reference(self):
        ref=np.zeros((2,4,3),dtype=np.uint8);mask=np.full((2,4),255,dtype=np.uint8);mask[0,0]=0
        source=ref.copy();source[0,0]=255
        check_pair(ref,mask,source,ref.copy(),mask.copy())
        source[1,0]=1
        with self.assertRaises(ValueError):check_pair(ref,mask,source,ref.copy(),mask.copy())
        altered=mask.copy();altered[1,0]=0
        with self.assertRaises(ValueError):check_pair(ref,mask,ref.copy(),ref.copy(),altered)

if __name__=='__main__': unittest.main()
