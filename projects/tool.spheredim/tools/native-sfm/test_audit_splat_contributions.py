import tempfile,unittest
from pathlib import Path
import numpy as np
from audit_splat_contributions import composite,read_header,sh3

class ContributionTest(unittest.TestCase):
    def test_front_to_back_and_threshold(self):
        w,t=composite([.5,.5,1/255,.25]);np.testing.assert_allclose(w,[.5,.25,0,.0625]);self.assertAlmostEqual(t,.1875)
    def test_clamp_and_early_stop(self):
        w,t=composite([1,1,1]);np.testing.assert_allclose(w,[.999,0,0]);self.assertAlmostEqual(t,.001)
    def test_dc_and_directional_basis(self):
        rest=np.zeros((1,3,15));rest[0,0,2]=1
        result=sh3(np.array([[1.,0,0]]),np.zeros((1,3)),rest)
        np.testing.assert_allclose(result,[[.5-.48860251190292,.5,.5]])
    def test_bad_headers_fail(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.ply'
            for b in (b'ply\nformat binary_little_endian 1.0\n',b'ply\nformat ascii 1.0\nelement vertex 1\nproperty float x\nend_header\n',b'ply\nformat binary_little_endian 1.0\nelement vertex 1\nproperty uchar red\nend_header\n'):
                p.write_bytes(b)
                with self.assertRaises(ValueError):read_header(p)

if __name__=='__main__':unittest.main()
