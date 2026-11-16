import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

from PIL import Image
import export_timestamp_probes as exporter


class TimestampExportTest(unittest.TestCase):
    def test_exact_timestamp_is_required_for_every_physical_lens_pass(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);source=root/'source.insv';source.write_bytes(b'fixture')
            def fake(cmd,env,text,capture_output):
                out=Path(cmd[cmd.index('--output')+1]);out.mkdir();mode=env['SPHEREDIM_OBSERVATION_MODE']
                value=255 if mode.startswith('mask') else 0
                image=Image.new('L' if mode.startswith('mask') else 'RGB',(4,2),value)
                image.save(out/'frame_0000000001000000.png')
                return types.SimpleNamespace(returncode=0,stdout=json.dumps({'backend':'GPU','outputs':[]}),stderr='SPHEREDIM_FRAME 1000000 1000000\n')
            args=['program','--source',str(source),'--output',str(root/'output'),'--indices','30','--timestamps','1.0']
            with patch('sys.argv',args),patch.object(exporter.subprocess,'run',side_effect=fake):exporter.main()
            manifest=json.loads((root/'output/manifest.json').read_text());frame=manifest['frames'][0]
            self.assertEqual((frame['frame'],frame['timestamp_microseconds']),(30,1000000))
            self.assertTrue(Path(frame['lens0']).is_file())
            self.assertEqual(manifest['selection'],'timestamps with seek')

            def wrong(cmd,env,text,capture_output):
                result=fake(cmd,env,text,capture_output);result.stderr='SPHEREDIM_FRAME 1000000 1033333\n';return result
            args[args.index('--output')+1]=str(root/'bad')
            with patch('sys.argv',args),patch.object(exporter.subprocess,'run',side_effect=wrong):
                with self.assertRaisesRegex(ValueError,'PTS'):exporter.main()


if __name__=='__main__':unittest.main()
