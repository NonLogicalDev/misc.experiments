import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

spec = importlib.util.spec_from_file_location('native_sfm_stage', Path(__file__).with_name('prepare_native_resolution_sfm.py'))
stage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage)


class NativeRigStageTest(unittest.TestCase):
    def test_pairs_and_conservative_feature_guard(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); native = root / 'native'; old = root / 'old'
            for lens in ('cam0', 'cam1'):
                for base, folder in ((native, 'images'), (native, 'masks'), (old, 'images'), (old, 'feature-masks')):
                    (base / folder / lens).mkdir(parents=True)
                name = 'frame_000001.png'
                (native / 'images' / lens / name).write_bytes(b'native-image')
                (old / 'images' / lens / name).write_bytes(b'old-image')
                guard = np.full((512, 1024), 255, np.uint8); guard[0, 0] = 0
                validity = np.full((1024, 2048), 255, np.uint8); validity[10, 10] = 0
                self.assertTrue(cv2.imwrite(str(old / 'feature-masks' / lens / name), guard))
                self.assertTrue(cv2.imwrite(str(native / 'masks' / lens / name), validity))
            for name in ('manifest.json', 'rig-metadata.json', 'rotation-priors.csv'): (old / name).write_text('{}')
            pair = root / 'pairs.tsv'; pair.write_text('cam0/frame_000001.png\tcam1/frame_000001.png\n')
            binary = root / 'binary'; binary.write_bytes(b'binary')
            out = root / 'output'
            with patch.object(stage.shutil, 'disk_usage', return_value=type('Disk', (), {'free': 100 * 1024**3})()):
                stage.prepare(native, old, pair, binary, out)
            result = cv2.imread(str(out / 'feature-masks/cam0/frame_000001.png'), cv2.IMREAD_GRAYSCALE)
            self.assertEqual(result[0, 0], 0); self.assertEqual(result[1, 1], 0)
            self.assertEqual(result[10, 10], 0); self.assertEqual(result[20, 20], 255)
            self.assertEqual((out / 'images/cam0/frame_000001.png').stat().st_ino, (native / 'images/cam0/frame_000001.png').stat().st_ino)
            self.assertFalse((out / 'INCOMPLETE').exists())
            (native / 'images/cam1/frame_000001.png').unlink(); (old / 'images/cam1/frame_000001.png').unlink()
            with patch.object(stage.shutil, 'disk_usage', return_value=type('Disk', (), {'free': 100 * 1024**3})()):
                with self.assertRaisesRegex(ValueError, 'synchronized'): stage.prepare(native, old, pair, binary, root / 'bad')


if __name__ == '__main__': unittest.main()
