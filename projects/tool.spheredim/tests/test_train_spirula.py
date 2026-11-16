"""Exercise the native-panorama guard and progress reporting without a GPU."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'train_spirula.py'


class TrainingGuardTests(unittest.TestCase):
    def run_mock(self, camera_line):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dataset = root / 'dataset'; dataset.mkdir()
            (dataset / 'manifest.json').write_text(json.dumps({'frames': [{'split': 'train'}, {'split': 'train'}]}))
            executable = root / 'trainer'
            executable.write_text('#!/bin/sh\nprintf "%s\\n" ' + repr(camera_line) + '\n' +
                "printf '%s\\n' 'step 1/2 (50%) splats 5 [elapsed 00:00:01 | ETA 00:00:01]' 'step 2/2 (100%) splats 5 [elapsed 00:00:02 | ETA 00:00:00]'\n")
            executable.chmod(0o755)
            progress = root / 'progress.json'
            run = subprocess.run([sys.executable, str(SCRIPT), str(executable), str(dataset),
                str(root / 'run'), str(progress), str(root / 'run.log'), '--iterations', '2'], capture_output=True, text=True)
            return run, json.loads(progress.read_text())

    def test_native_run_reports_completion(self):
        run, progress = self.run_mock('Cameras: 2 (2 after splitting)')
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(progress['status'], 'complete')
        self.assertEqual(progress['iteration'], 2)

    def test_unexpected_split_is_rejected(self):
        run, progress = self.run_mock('Cameras: 2 (12 after splitting)')
        self.assertNotEqual(run.returncode, 0)
        self.assertEqual(progress['status'], 'error')
        self.assertIn('Camera count mismatch', progress['error'])


if __name__ == '__main__': unittest.main()
