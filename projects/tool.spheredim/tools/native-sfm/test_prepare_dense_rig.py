from fractions import Fraction
import os
from pathlib import Path
import tempfile
import unittest
import sys
from unittest.mock import patch
import prepare_dense_rig as dense
from prepare_dense_rig import disk_usage, matched_pts


class DenseRigTest(unittest.TestCase):
    def test_monitor_stops_export_when_incremental_budget_is_exceeded(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name); output=root/'output.bin';log=root/'log.txt'
            code=f"from pathlib import Path; import time; Path({str(output)!r}).write_bytes(b'x'*64); time.sleep(10)"
            with patch.object(dense,'RESERVE',0), patch.object(dense,'BUDGET',16):
                with self.assertRaisesRegex(RuntimeError,'cap'):
                    dense.monitor([sys.executable,'-c',code],os.environ.copy(),root,set(),log,10)

    def test_packet_times_require_one_match_in_each_lens(self):
        streams={0:Fraction(1,30000),1:Fraction(1,30000)}
        rows=matched_pts(500500,streams,{0:[15015],1:[15015]})
        self.assertEqual([x['pts'] for x in rows],[15015,15015])
        with self.assertRaises(ValueError):matched_pts(500500,streams,{0:[15015,15015],1:[15015]})
        with self.assertRaises(ValueError):matched_pts(500500,streams,{0:[15015],1:[]})

    def test_budget_counts_unique_new_inodes_not_baseline_links(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);base=root/'base';base.write_bytes(b'abc');st=base.stat();excluded={(st.st_dev,st.st_ino)}
            out=root/'out';out.mkdir();os.link(base,out/'baseline')
            extra=out/'extra';extra.write_bytes(b'12345');os.link(extra,out/'duplicate')
            self.assertEqual(disk_usage(out,excluded),5)


if __name__=='__main__':unittest.main()
