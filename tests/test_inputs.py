import importlib.util
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('spheredim', Path(__file__).parents[1] / 'src' / 'spheredim.py')
spheredim = importlib.util.module_from_spec(spec)
spec.loader.exec_module(spheredim)

class InputTests(unittest.TestCase):
    def test_missing_video_does_not_create_output(self):
        with tempfile.TemporaryDirectory() as root:
            output = Path(root) / 'output'
            with self.assertRaisesRegex(ValueError, 'Video does not exist'):
                spheredim.run(Path(root) / 'missing.mp4', output, 2, 1024, 10)
            self.assertFalse(output.exists())

    def test_nonempty_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            video = root / 'video.mp4'
            video.touch()
            output = root / 'output'
            output.mkdir()
            original = output / 'important.txt'
            original.write_text('preserve me')
            with self.assertRaisesRegex(ValueError, 'not empty'):
                spheredim.run(video, output, 2, 1024, 10)
            self.assertEqual(original.read_text(), 'preserve me')

    def test_invalid_sampling_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            video = Path(root) / 'video.mp4'
            video.touch()
            with self.assertRaisesRegex(ValueError, 'Sampling rate'):
                spheredim.run(video, Path(root) / 'output', float('nan'), 1024, 10)

if __name__ == '__main__':
    unittest.main()
