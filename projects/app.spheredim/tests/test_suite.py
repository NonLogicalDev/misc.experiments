import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class SuiteSafetyTest(unittest.TestCase):
    def test_nonempty_results_directory_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'results'
            output.mkdir()
            marker = output / 'keep.txt'
            marker.write_text('keep')
            script = Path(__file__).with_name('run_synthetic_suite.py')
            result = subprocess.run([sys.executable, str(script), str(output)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('absent or empty', result.stderr)
            self.assertEqual(marker.read_text(), 'keep')


if __name__ == '__main__':
    unittest.main()
