import unittest
from build_rig_pair_graph import build_graphs,names

class PairGraphTests(unittest.TestCase):
    def test_exhaustive_shared_and_temporal_union(self):
        base,dense,temporal,sync=build_graphs([0,2],[0,1,2],overlap=1,sync_pairs=True)
        self.assertEqual(len(base),6)
        self.assertTrue(base<=dense)
        self.assertEqual(len(temporal),4)
        self.assertEqual(len(sync),3)
        self.assertEqual(len(dense),11)
        self.assertEqual(set(names([0,2])),set(x for pair in base for x in pair))
    def test_rejects_missing_or_duplicate_frames(self):
        for shared,dense in (([0,2],[0,1]),([0,0],[0,1]),([0,1],[0,1,1])):
            with self.assertRaises(ValueError):build_graphs(shared,dense)

if __name__=='__main__':unittest.main()
