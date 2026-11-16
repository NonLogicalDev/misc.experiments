import json,sys,tempfile,unittest,struct
from pathlib import Path
from unittest.mock import patch
import run_splat as r

PROPS=['x','y','z','opacity','scale_0','scale_1','scale_2','rot_0','rot_1','rot_2','rot_3']
HEADER=('ply\nformat binary_little_endian 1.0\nelement vertex 2\n'+''.join('property float '+p+'\n' for p in PROPS)+'end_header\n').encode()
PLY=HEADER+struct.pack('<22f',*([0]*22))

class RunnerTests(unittest.TestCase):
 def run_case(self,code,**kwargs):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);result=r.monitor([sys.executable,'-u','-c',code],p/'output',p/'status.json',p/'run.log',2,total=3,reserve=0,interval=.02,timeout=4,**kwargs)
   self.assertEqual(json.loads((p/'status.json').read_text())['status'],result['status']);return result
 def test_bounded_schedule(self):
  for iterations,save in ((3000,1000),(10000,5000)):r.prep.validate_schedule(iterations,save)
  for iterations,save in ((0,1),(5,6),(100001,1),(3,-1),(True,1)):
   with self.assertRaises(ValueError):r.prep.validate_schedule(iterations,save)
 def test_success(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);out=p/'output';code="from pathlib import Path; p=Path(%r)/'step-3.ckpt';p.mkdir(parents=True);(p/'splat.ply').write_bytes(%r);print('Cameras: 2 (2 after splitting)');print('step 3/3')" % (str(out),PLY)
   result=r.monitor([sys.executable,'-u','-c',code],out,p/'status',p/'log',2,total=3,reserve=0,interval=.02,timeout=4);self.assertEqual(result['status'],'complete');self.assertEqual(len(result['checkpoints']),1)
 def test_missing_step_and_camera_mismatch(self):
  self.assertEqual(self.run_case("print('Cameras: 2 (2 after splitting)')")['status'],'error')
  result=self.run_case("import time;print('Cameras: 2 (3 after splitting)');time.sleep(2)")
  self.assertIn('Camera count mismatch',result['error'])
 def test_output_cap_even_if_silent(self):
  result=self.run_case("import time;print('x'*5000);time.sleep(2)",limit=1000)
  self.assertEqual(result['error'],'Output size limit exceeded')
 def test_nonzero_exit_and_unterminated_output(self):
  self.assertEqual(self.run_case("import sys;print('Cameras: 2 (2 after splitting)');print('step 3/3');sys.exit(7)")['status'],'error')
  self.assertEqual(self.run_case("import os,time;os.write(1,b'x'*5000);time.sleep(2)",limit=1000)['error'],'Output size limit exceeded')
 def test_timeout_silent_process(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);result=r.monitor([sys.executable,'-c','import time;time.sleep(2)'],p/'out',p/'status',p/'log',2,total=3,reserve=0,interval=.02,timeout=.1)
   self.assertEqual(result['error'],'Training timeout exceeded')
 def test_checkpoint_stability_and_activity(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);output=p/'run';ck=output/'step-1000.ckpt';ck.mkdir(parents=True);ply=ck/'splat.ply';ply.write_bytes(PLY[:-4]);seen,ready=r.checkpoints(output,{});self.assertEqual(ready,[]);seen,ready=r.checkpoints(output,seen);self.assertEqual(ready,[],'paused truncated file must remain unpublished');ply.write_bytes(PLY)
   seen,ready=r.checkpoints(output,{});self.assertEqual(ready,[])
   seen,ready=r.checkpoints(output,seen);self.assertEqual(ready,[(1000,ply)])
   ply.write_bytes(PLY+b'x');seen,ready=r.checkpoints(output,seen);self.assertEqual(ready,[])
   _,ready=r.checkpoints(output,seen,final=True);self.assertEqual(ready,[],'final checkpoint must also be complete')
   ply.write_bytes(PLY);_,ready=r.checkpoints(output,{},final=True);self.assertEqual(ready,[(1000,ply)])
   activity=p/'activity.json';activity.write_text(json.dumps({'trajectory':{'poses':'unchanged'},'artifacts':{'mesh':'keep'}}))
   state={'status':'running','current':1000,'total':3000,'error':None};r.publish_activity(activity,state,output,p/'train.log',ready);value=json.loads(activity.read_text())
   self.assertEqual(value['trajectory']['poses'],'unchanged');self.assertEqual(value['artifacts']['mesh'],'keep');self.assertEqual(value['artifacts']['splat'],{'file':'run/step-1000.ckpt/splat.ply','run':'run','checkpoint':1000});self.assertEqual(value['logs'][0]['file'],'train.log');self.assertEqual(value['currentActivity'],0)
   state['status']='complete';state['current']=3000;r.publish_activity(activity,state,output,p/'train.log',ready);value=json.loads(activity.read_text());self.assertEqual(value['currentActivity'],1);self.assertEqual(value['stages'][1]['status'],'pending')
   state.update(status='error',error='failure');r.publish_activity(activity,state,output,p/'train.log',[]);value=json.loads(activity.read_text());self.assertEqual(value['stages'][0]['status'],'failed');self.assertIsNone(value['artifacts']['splat'])
 def test_reject_unsupported_ply(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'splat.ply'
   for content in (PLY.replace(b'binary_little_endian',b'ascii'),PLY.replace(b'property float x',b'property list float x'),PLY.replace(b'property float x',b'property double x'),PLY.replace(b'property float x',b'property float y')):
    p.write_bytes(content);self.assertIsNone(r.complete_splat_ply(p))
 def test_no_overwrite(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);(p/'status').write_text('existing')
   with self.assertRaises(FileExistsError):r.monitor([sys.executable],p/'out',p/'status',p/'log',2,reserve=0)
   self.assertEqual((p/'status').read_text(),'existing')
if __name__=='__main__':unittest.main()
