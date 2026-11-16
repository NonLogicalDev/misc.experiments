import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

import audit_training_views as audit


class AuditPreparationTests(unittest.TestCase):
    def fixture(self, root, step=10000, final_step=10000):
        source = root / 'source'; run = root / 'original'; ckpt = run / f'step-{final_step:09d}.ckpt'
        (source / 'sparse/0').mkdir(parents=True); (source / 'images').mkdir(); (source / 'masks').mkdir(); ckpt.mkdir(parents=True)
        names = [f'{split}_{frame:06d}_cam{lens}.png' for split, frame in [('eval', 0), ('eval', 120), ('train', 15)] for lens in (0, 1)]
        binary = root / 'trainer'; binary.write_bytes(b'trainer')
        for folder in ('images', 'masks'):
            for name in names: (source / folder / name).write_bytes(name.encode())
        for file in ('cameras.txt', 'points3D.txt'): (source / 'sparse/0' / file).write_text('fixture\n')
        (source / 'seed.ply').write_text('fixture\n')
        (source / 'sparse/0/images.txt').write_text(''.join(f'{i} 1 0 0 0 0 0 0 1 {name}\n\n' for i, name in enumerate(names)))
        (source / 'manifest.json').write_text(json.dumps({'frames': [{'name': n} for n in names], 'heldout_evaluation_order': names[:4], 'command': [str(binary)], 'binary_sha256': audit.sha(binary)}))
        (run / 'config.json').write_text(json.dumps({'num_iterations': final_step, 'mask_boundary_offset': 0, 'warp_to_pinhole': False, 'warp_spherical_to_pinhole': False, 'use_calib_warp': False}))
        content = json.dumps({'step': step, 'full_resume': 1}).encode()
        with tarfile.open(ckpt / 'state.tar', 'w') as t:
            info = tarfile.TarInfo('state.json'); info.size = len(content); t.addfile(info, io.BytesIO(content))
        (ckpt / 'splat.ply').write_bytes(b'ply')
        return source, run, names

    def test_zero_step_command_and_preserved_inputs(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); source, run, names = self.fixture(root)
            before = (source / 'sparse/0/images.txt').read_bytes()
            plan = audit.prepare(source, run, root / 'out', [15])
            cmd = plan['command']
            for key, value in (('--num-iterations', '10000'), ('--steps-per-save', '0'), ('--mask-boundary-offset', '0'), ('--warp-to-pinhole', '0')):
                self.assertEqual(cmd[cmd.index(key) + 1], value)
            self.assertEqual((source / 'sparse/0/images.txt').read_bytes(), before)
            self.assertEqual(len(plan['rename']), 4)
            for name in names:
                self.assertTrue((root / 'out/data/images' / plan['rename'].get(name, name)).samefile(source / 'images' / name))

    def test_uses_original_final_step(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); source, run, _ = self.fixture(root, step=4000, final_step=4000)
            plan = audit.prepare(source, run, root / 'out', [15])
            self.assertEqual(plan['checkpoint_step'], 4000)
            cmd = plan['command']
            self.assertEqual(cmd[cmd.index('--num-iterations') + 1], '4000')
            self.assertTrue(cmd[cmd.index('--resume') + 1].endswith('step-000004000.ckpt'))

    def test_requires_retained_control_before_creating_output(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); source, run, names = self.fixture(root)
            manifest_path = source / 'manifest.json'
            manifest = json.loads(manifest_path.read_text()); manifest['heldout_evaluation_order'] = names[:2]
            manifest_path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, 'Not enough'):
                audit.prepare(source, run, root / 'out', [15])
            self.assertFalse((root / 'out').exists())

    def test_rejects_wrong_checkpoint_before_creating_output(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); source, run, _ = self.fixture(root, step=9999)
            with self.assertRaisesRegex(ValueError, 'original final step'):
                audit.prepare(source, run, root / 'out', [15])
            self.assertFalse((root / 'out').exists())


if __name__ == '__main__':
    unittest.main()
