import importlib.util
from pathlib import Path
import tempfile
spec=importlib.util.spec_from_file_location('prepare_splat',Path(__file__).with_name('prepare_splat.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
s=m.split_frames([30,0,15,45,60,75,90,105,120],8)
assert [f for f in sorted(s) if s[f]=='eval']==[0,120]
assert all(s[f] in ('train','eval') for f in s)
for frames,interval in [([1,1],8),([1],8),([1,2],1)]:
 try:m.split_frames(frames,interval)
 except ValueError:pass
 else:raise AssertionError('Invalid input accepted')
with tempfile.TemporaryDirectory() as d:
 try:m.read_model(Path(d))
 except FileNotFoundError:pass
 else:raise AssertionError('Missing model accepted')
print('PASS paired timestamp holdouts and invalid input checks')
