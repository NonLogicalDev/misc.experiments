import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

import cv2
import numpy as np
import export_timestamp_probes as exporter


class TimestampExportTest(unittest.TestCase):
    def test_exact_timestamp_is_required_for_every_physical_lens_pass(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);source=root/'source.insv';source.write_bytes(b'fixture')
            def fake(cmd,env,text,capture_output):
                out=Path(cmd[cmd.index('--output')+1]);out.mkdir();mode=env['SPHEREDIM_OBSERVATION_MODE']
                value=255 if mode.startswith('mask') else 0
                width=int(cmd[cmd.index('--width')+1])
                image=np.full((width//2,width) if mode.startswith('mask') else (width//2,width,3),value,np.uint8)
                cv2.imwrite(str(out/'frame_0000000001000000.png'),image)
                return types.SimpleNamespace(returncode=0,stdout=json.dumps({'backend':'GPU','outputs':[]}),stderr='SPHEREDIM_FRAME 1000000 1000000\n')
            args=['program','--source',str(source),'--output',str(root/'output'),'--indices','30','--timestamps','1.0','--width','1024']
            with patch('sys.argv',args),patch.object(exporter.subprocess,'run',side_effect=fake):exporter.main()
            manifest=json.loads((root/'output/manifest.json').read_text());frame=manifest['frames'][0]
            self.assertEqual((frame['frame'],frame['timestamp_microseconds']),(30,1000000))
            self.assertTrue(Path(frame['lens0']).is_file())
            self.assertEqual(manifest['selection'],'timestamps with seek')

            self.assertEqual((manifest['width'],manifest['height']),(1024,512))

            def small(cmd,env,text,capture_output):
                result=fake(cmd,env,text,capture_output)
                out=Path(cmd[cmd.index('--output')+1])
                path=out/'frame_0000000001000000.png'
                image=cv2.imread(str(path)); cv2.imwrite(str(path),cv2.resize(image,(4,2)))
                return result
            args[args.index('--output')+1]=str(root/'wrong-size')
            with patch('sys.argv',args),patch.object(exporter.subprocess,'run',side_effect=small):
                with self.assertRaisesRegex(ValueError,'support'):exporter.main()

            def wrong(cmd,env,text,capture_output):
                result=fake(cmd,env,text,capture_output);result.stderr='SPHEREDIM_FRAME 1000000 1033333\n';return result
            args[args.index('--output')+1]=str(root/'bad')
            with patch('sys.argv',args),patch.object(exporter.subprocess,'run',side_effect=wrong):
                with self.assertRaisesRegex(ValueError,'PTS'):exporter.main()

    def test_early_seek_keeps_actual_timestamp_strict(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name); source=root/'source'; source.write_bytes(b'fixture')
            def fake(cmd,env,text,capture_output):
                out=Path(cmd[cmd.index('--output')+1]); out.mkdir()
                mask=env['SPHEREDIM_OBSERVATION_MODE'].startswith('mask')
                image=np.full((512,1024) if mask else (512,1024,3),255 if mask else 0,np.uint8)
                cv2.imwrite(str(out/'frame_0000000000999999.png'),image)
                return types.SimpleNamespace(returncode=0,stdout=json.dumps({'backend':'GPU','outputs':[]}),stderr='SPHEREDIM_FRAME 999999 1000000\n')
            args=['program','--source',str(source),'--output',str(root/'output'),'--indices','30','--timestamps','1.0','--width','1024','--seek-early-us','1']
            with patch('sys.argv',args),patch.object(exporter.subprocess,'run',side_effect=fake): exporter.main()
            data=json.loads((root/'output/manifest.json').read_text())
            self.assertEqual(data['frames'][0]['timestamp_microseconds'],1000000)
            self.assertEqual(data['seek_early_us'],1)



if __name__=='__main__':unittest.main()
