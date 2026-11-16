import copy
import json
from pathlib import Path
import tempfile
import unittest
from run_rig_pair import command, validate_configs


class ConfigTests(unittest.TestCase):
    def test_explicit_executable_modes(self):
        args = [Path('/bin/example'), Path('/data'), Path('/out'), Path('/data/rig.json')]
        self.assertEqual(command(*args)[:3], ['/bin/example', 'sfm', 'auto'])
        self.assertEqual(command(*args, standalone=True)[:3], ['/bin/example', 'auto', '/data/images'])
        default = command(*args)
        cpu = command(*args, ba_real='cpu')
        for flag in ('--ba-real', '--ba-real-coarse'):
            self.assertEqual(default[default.index(flag)+1], 'float')
            self.assertEqual(cpu[cpu.index(flag)+1], 'cpu')

    def test_only_translation_may_change(self):
        base = {'rigs': [{'members': [{}, {'prefix': 'cam1', 'rotation': [1, 0, 0, 0], 'translation': [0, 0, 0], 'fixed': True, 'refine': 'none'}]}]}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'rig-zero.json').write_text(json.dumps(base))
            changed = copy.deepcopy(base)
            member = changed['rigs'][0]['members'][1]
            member['translation'] = [.01, 0, .03]
            (root / 'rig-metadata.json').write_text(json.dumps(changed))
            validate_configs(root, ['zero', 'metadata'])
            member['rotation'] = [0, 1, 0, 0]
            (root / 'rig-metadata.json').write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError, 'only in cam1 translation'):
                validate_configs(root, ['zero', 'metadata'])


if __name__ == '__main__':
    unittest.main()
