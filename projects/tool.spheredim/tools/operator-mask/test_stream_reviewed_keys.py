import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import cv2
import numpy as np
from warp_sequence import spherical_guard, warp


class StreamReviewedKeysTest(unittest.TestCase):
    def test_nonzero_start_and_other_cadence(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); video=root/'source.mp4'
            subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-f','lavfi','-i','testsrc=size=1024x512:rate=10:duration=1','-c:v','mpeg4','-pix_fmt','yuv420p',str(video)],check=True)
            fused=root/'fused.csv'
            with fused.open('w',newline='') as f:
                w=csv.DictWriter(f,fieldnames=['frame','video_pts_s','q_x','q_y','q_z','q_w','heading_rad']);w.writeheader()
                for i in range(10):w.writerow({'frame':i,'video_pts_s':i/10,'q_x':0,'q_y':0,'q_z':0,'q_w':1,'heading_rad':0})
            raw=root/'raw';raw.mkdir();review=root/'review';(review/'masks').mkdir(parents=True)
            exclude=np.zeros((512,1024),np.uint8);exclude[100:120,100:120]=255
            keep=255-spherical_guard(warp(spherical_guard(exclude,4),np.eye(3)),32)
            frames=[]
            for ordinal,n in enumerate((2,8)):
                cv2.imwrite(str(raw/f'frame_{ordinal:05d}.png'),255-exclude)
                name=f'frame_{n:06d}.png';cv2.imwrite(str(review/'masks'/name),keep)
                frames.append({'source_frame':n,'video_pts_s':n/10,'mask':name})
            manifest=review/'manifest.json';manifest.write_text(json.dumps({'frames':frames}))
            script=Path(__file__).with_name('stream_reviewed_keys.py')
            subprocess.run([sys.executable,str(script),str(video),str(video),str(fused),str(raw),str(manifest),str(root/'output'),'--sample-stride','2'],check=True,timeout=60)
            output=json.loads((root/'output/manifest.json').read_text())
            self.assertEqual([x['source_frame'] for x in output['frames']],[2,4,6,8])
            self.assertEqual([x['keyframe'] for x in output['frames']],[True,False,False,True])
            self.assertEqual(output['key_stride'],6)


if __name__ == '__main__':unittest.main()
