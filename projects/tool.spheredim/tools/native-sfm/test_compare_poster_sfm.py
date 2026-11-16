import unittest
import compare_poster_sfm as p
class PosterComparisonTests(unittest.TestCase):
 def test_reference_grid_maps_source_roi_edges(self):
  self.assertEqual(p.cell((450,440)),(0,0));self.assertEqual(p.cell((699.9,689.9)),(3,3));self.assertEqual(p.cell((575,565)),(2,2))
if __name__=='__main__':unittest.main()
