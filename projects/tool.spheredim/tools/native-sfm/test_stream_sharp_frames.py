import os, sys, tempfile, time, unittest
from pathlib import Path
from unittest.mock import Mock, patch
import stream_sharp_frames as s

FAKE='''import os,sys,time\nfrom pathlib import Path
from unittest.mock import Mock, patch\nout=Path(sys.argv[1]);out.mkdir(parents=True)\nmode=os.environ["SPHEREDIM_OBSERVATION_MODE"]\nfor t in (100,200,300):\n time.sleep(.08 if mode=="mask1" else .005)\n print("SPHEREDIM_FRAME",t-1,t if mode!="bad" else t+1,flush=True)\n p=out/f"frame_{t-1:016d}.png";q=p.with_suffix(".tmp");q.write_bytes(b"abc");q.rename(p)\nprint('{\"backend\":\"GPU\"}',flush=True)\n'''
class StreamTests(unittest.TestCase):
 def commands(self,root,source=FAKE):
  script=root/'producer.py';script.write_text(source)
  return {m:[sys.executable,str(script),str(root/'spool'/m)] for m in s.MODES}
 def test_signal_exit_race_is_only_ignored_for_reaped_child(self):
  proc=Mock(pid=123);proc.poll.return_value=0
  with patch.object(s.os,'killpg',side_effect=PermissionError):self.assertFalse(s.signal_owned_group(proc,s.signal.SIGSTOP))
  proc.poll.return_value=None
  with patch.object(s.os,'killpg',side_effect=PermissionError):
   with self.assertRaises(PermissionError):s.signal_owned_group(proc,s.signal.SIGSTOP)
 def test_uneven_and_slow_mask(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);seen=[]
   for t,files,stats in s.stream_frames(self.commands(p),p/'spool',[100,200,300],reserve=0,interval=.005,timeout=5,lead=1,low_water=5,cap=100):
    self.assertEqual({x.read_bytes() for x in files.values()},{b'abc'});seen.append(t)
   self.assertEqual(seen,[100,200,300]);self.assertFalse((p/'spool').exists())
 def test_zero_timestamp(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);source=FAKE.replace('(100,200,300)','(0,)').replace('t-1','max(0,t-1)');cmd=self.commands(p,source)
   self.assertEqual([t for t,_,_ in s.stream_frames(cmd,p/'spool',[0],reserve=0,interval=.005,timeout=5,lead=1,low_water=5,cap=100)],[0])
 def test_slow_consumer_and_close(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);stream=s.stream_frames(self.commands(p),p/'spool',[100,200,300],reserve=0,interval=.005,timeout=5,lead=1,low_water=5,cap=100)
   next(stream);time.sleep(.05);before=sum(x.stat().st_size for x in (p/'spool').rglob('*') if x.is_file());time.sleep(.2);after=sum(x.stat().st_size for x in (p/'spool').rglob('*') if x.is_file());self.assertEqual(before,after)
   stream.close();self.assertFalse((p/'spool').exists())
 def test_cpu_backend_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);cmd=self.commands(p,FAKE.replace('GPU','CPU'))
   with self.assertRaisesRegex(ValueError,'GPU backend'):list(s.stream_frames(cmd,p/'spool',[100,200,300],reserve=0,interval=.005,timeout=5,lead=1,low_water=5,cap=100))
   self.assertFalse((p/'spool').exists())
 def test_excess_output_after_last_frame(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);extra=FAKE+'''\nif mode=="mask1":\n while True:\n  (out/"late.tmp").write_bytes(b"x"*200)\n  time.sleep(.01)\n''';cmd=self.commands(p,extra)
   with self.assertRaisesRegex(RuntimeError,'spool cap'):list(s.stream_frames(cmd,p/'spool',[100,200,300],reserve=0,interval=.005,timeout=5,lead=1,low_water=5,cap=100))
   self.assertFalse((p/'spool').exists())
 def test_fast_final_oversize_detected(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);extra=FAKE+'''\nif mode=="mask1": (out/"late.tmp").write_bytes(b"x"*200)\n''';cmd=self.commands(p,extra)
   with self.assertRaisesRegex(RuntimeError,'spool cap'):list(s.stream_frames(cmd,p/'spool',[100,200,300],reserve=0,interval=.05,timeout=5,lead=1,low_water=5,cap=100))
   self.assertFalse((p/'spool').exists())
 def test_missing_mask_output_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);fake=FAKE.replace('q.write_bytes(b"abc");q.rename(p)','q.write_bytes(b"abc");q.rename(p) if mode!="mask1" else q.unlink()');cmd=self.commands(p,fake)
   with self.assertRaisesRegex(RuntimeError,'ended before complete pair'):list(s.stream_frames(cmd,p/'spool',[100,200,300],reserve=0,interval=.005,timeout=5,lead=3,low_water=50,cap=100))
   self.assertFalse((p/'spool').exists())
 def test_report_limit_atomic(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'report.json'
   with self.assertRaisesRegex(ValueError,'size limit'):s.write_json_bounded(p,{'large':'x'*100},limit=10)
   self.assertFalse(p.exists());self.assertEqual(list(p.parent.iterdir()),[])
   s.write_json_bounded(p,{'ok':True},limit=100);self.assertTrue(p.exists())
   with self.assertRaises(FileExistsError):s.write_json_bounded(p,{'overwrite':True})
 def test_unknown_timestamp_and_cleanup(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);cmd=self.commands(p,FAKE.replace('t if mode!="bad" else t+1','t+1 if mode=="mask1" else t'))
   with self.assertRaisesRegex(ValueError,'mismatched timestamp'):list(s.stream_frames(cmd,p/'spool',[100,200,300],reserve=0,interval=.005,timeout=5,lead=1,low_water=5,cap=100))
   self.assertFalse((p/'spool').exists())
 def test_worker_failure_and_cleanup(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);cmd=self.commands(p,FAKE.replace('for t in (100,200,300):','if mode=="mask1": sys.exit(7)\nfor t in (100,200,300):'))
   with self.assertRaisesRegex(RuntimeError,'worker exited'):list(s.stream_frames(cmd,p/'spool',[100,200,300],reserve=0,interval=.005,timeout=5,lead=1,low_water=5,cap=100))
   self.assertFalse((p/'spool').exists())
if __name__=='__main__':unittest.main()
