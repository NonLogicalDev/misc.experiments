"""Synthetic smoke tests for native-ERP preparation and command construction."""
import cv2,json,signal,subprocess,sys,tempfile,time
import numpy as np
from pathlib import Path
here=Path(__file__).resolve().parent
with tempfile.TemporaryDirectory(prefix='spheredim-erp-tools-') as d:
 root=Path(d);video=root/'source.mkv';mask=root/'mask.mkv';badmask=root/'short.mkv'
 def write(path,n,masked=False):
  v=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*'FFV1'),10,(64,32))
  assert v.isOpened()
  for i in range(n):
   arr=np.full((32,64,3),i*20,dtype=np.uint8)
   if masked:arr[:8]=255;arr[8:]=0
   v.write(arr)
  v.release()
 write(video,5);write(mask,5,True);write(badmask,4,True)
 out=root/'dataset';status=root/'status.json';log=root/'run.log'
 cmd=[sys.executable,str(here/'prepare.py'),str(video),str(mask),str(out),'--mask-polarity','white-exclude','--status',str(status),'--log',str(log),'--guard-pixels','2','--min-free-gib','0']
 res=subprocess.run(cmd,capture_output=True,text=True);assert res.returncode==0,res.stderr
 manifest=json.loads((out/'manifest.json').read_text());assert manifest['frame_count']==5 and manifest['width']==64 and len(manifest['frames'])==5
 assert len(list((out/'images').glob('*.png')))==5 and len(list((out/'masks').glob('*.png')))==5
 m=cv2.imread(str(out/'masks'/'frame_000000.png'),cv2.IMREAD_GRAYSCALE);assert m[0,32]==0 and m[9,32]==0 and m[11,32]==255
 assert json.loads(status.read_text())['stage']=='frames ready'
 out2=root/'invalid';bad=cmd.copy();bad[3]=str(badmask);bad[4]=str(out2);res=subprocess.run(bad,capture_output=True,text=True);assert res.returncode!=0 and not out2.exists()
 runner=[sys.executable,str(here/'run_sfm.py'),'/usr/bin/true',str(out),str(root/'workspace'),'--native-progress',str(root/'np'),'--status',str(status),'--log',str(log),'--min-free-gib','0','--dry-run']
 res=subprocess.run(runner,capture_output=True,text=True);assert res.returncode==0,res.stderr;config=json.loads(res.stdout);args=config['command'];assert config['image_count']==5 and config['size']==[64,32]
 for flag,value in [('--camera-model','equirectangular'),('--max-image-size','64'),('--pairs','sequential'),('--prefilter-neighbors','8')]:assert args[args.index(flag)+1]==value
 assert '--quadratic-overlap' in args and '--no-loop-closure' not in args
 fake=root/'fake-spirula';fake.write_text('''#!/usr/bin/env python3
import pathlib,struct,sys,time
p=pathlib.Path(sys.argv[sys.argv.index('--progress-dir')+1]);p.mkdir(parents=True,exist_ok=True)
(p/'status.bin').write_bytes(struct.pack('<4sIII6qd',b'VKPS',1,2,4,5,5,3,5,7,1,.5))
print('[match] synthetic test',flush=True);time.sleep(1.5)
''');fake.chmod(0o755)
 running=runner.copy();running[2]=str(fake);running.remove('--dry-run');res=subprocess.run(running,capture_output=True,text=True);assert res.returncode==0,res.stderr
 st=json.loads(status.read_text());assert st['status']=='complete' and st['registered']==3 and st['points']==7
 fake.write_text(fake.read_text().replace('time.sleep(1.5)','time.sleep(30)'))
 proc=subprocess.Popen(running,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
 time.sleep(1.4);proc.send_signal(signal.SIGINT);proc.communicate(timeout=5)
 assert proc.returncode==130 and json.loads(status.read_text())['status']=='paused'
 # Refuse inconsistent image/mask resolutions rather than silently changing projection.
 cv2.imwrite(str(out/'masks'/'frame_000002.png'),np.zeros((20,20),np.uint8));res=subprocess.run(runner,capture_output=True,text=True);assert res.returncode!=0
 print('PASS exact frame/mask count, conservative white-keep mask, timestamps, no-view-splitting ERP command, and resolution guard')
