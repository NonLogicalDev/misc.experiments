import struct
import tempfile
import unittest
from pathlib import Path
from recover_landmark_descriptors import recover


def pack(fmt, *v):
    return struct.pack('<' + fmt, *v)


def fixture(root):
    workspace = root / 'workspace'
    model = workspace / 'sparse' / '0'
    features = workspace / 'features' / 'cam0'
    model.mkdir(parents=True)
    features.mkdir(parents=True)
    # Two distinct orientations share one coordinate. Only rows 1 and 2 are
    # referenced, so compact row 0 must recover descriptor 1, not descriptor 0.
    keypoints = [(10., 20., 1., 0.), (10., 20., 1., 2.), (30., 40., 2., 1.)]
    (features / 'frame.bin').write_bytes(pack('4s6I', b'VKFT', 6, 1024, 512, 3, 128, 0) + b''.join(pack('4f', *k) for k in keypoints) + b''.join(bytes([i]) * 128 for i in range(3)))
    name = b'cam0/frame'
    other = b'cam1/other'
    (workspace / 'matches.bin').write_bytes(pack('4sII', b'VKMT', 5, 2) + pack('I', len(name)) + name + pack('I', 3) + pack('I', len(other)) + other + pack('I', 2) + pack('I', 1) + pack('IIiI', 0, 1, 1, 2) + pack('IIII', 1, 0, 2, 1))
    image = pack('Q', 1) + pack('i7di', 1, 1., 0., 0., 0., 0., 0., 0., 1) + name + b'.png\0' + pack('Q', 2) + pack('ddq', 10., 20., 7) + pack('ddq', 30., 40., 8)
    (model / 'images.bin').write_bytes(image)
    def point(pid, index):
        return pack('Q3d3BdQII', pid, float(pid), 0., 1., 1, 2, 3, 0., 1, 1, index)
    (model / 'points3D.bin').write_bytes(pack('Q', 2) + point(7, 0) + point(8, 1))
    return model, workspace


class RecoveryTest(unittest.TestCase):
    def test_indexed_compaction_preserves_duplicate_coordinates(self):
        with tempfile.TemporaryDirectory() as tmp:
            model, workspace = fixture(Path(tmp))
            rows = recover(model, workspace, ['cam0/frame.png'])
            self.assertEqual([r.feature_index for r in rows], [1, 2])
            self.assertEqual([r.descriptor[0] for r in rows], [1, 2])
            self.assertEqual([r.point_id for r in rows], [7, 8])
            self.assertEqual(rows[0].orientation, 2.)

    def test_rejects_missing_reciprocal_track(self):
        with tempfile.TemporaryDirectory() as tmp:
            model, workspace = fixture(Path(tmp))
            data = bytearray((model / 'points3D.bin').read_bytes())
            data[-4:] = pack('I', 0)
            (model / 'points3D.bin').write_bytes(data)
            with self.assertRaisesRegex(ValueError, 'track|reciprocal'):
                recover(model, workspace, ['cam0/frame.png'])

    def test_rejects_coordinate_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            model, workspace = fixture(Path(tmp))
            data = bytearray((model / 'images.bin').read_bytes())
            offset = 8 + 64 + len(b'cam0/frame.png\0') + 8
            data[offset:offset+8] = pack('d', 11.)
            (model / 'images.bin').write_bytes(data)
            with self.assertRaisesRegex(ValueError, 'coordinate mismatch'):
                recover(model, workspace, ['cam0/frame.png'])


if __name__ == '__main__':
    unittest.main()
