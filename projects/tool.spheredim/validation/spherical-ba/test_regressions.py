#!/usr/bin/env python3
"""Deterministic spherical BA tests: observable case and disconnected counterexample."""
import json,subprocess,sys,tempfile
from pathlib import Path
here=Path(__file__).resolve().parent
with tempfile.TemporaryDirectory(prefix='spheredim-synthetic-test-',dir='/private/tmp') as d:
 root=Path(d)
 def run(name,*args):
  out=root/name
  subprocess.run([sys.executable,str(here/'test_synthetic.py'),'--output',str(out),*args],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  return json.loads((out/'metrics.json').read_text())
 good=run('observable','--seed','41','--triangulate-initial','--local-track-length','3')
 assert good['graph_components']==[32] and good['termination'].endswith('.CONVERGENCE')
 assert good['pose_after']['position_rms']<good['pose_before']['position_rms']
 assert good['pose_after']['rotation_median_degrees']<good['pose_before']['rotation_median_degrees']
 assert good['heldout_after']['mean_px']<good['heldout_before']['mean_px']
 bad=run('disconnected','--seed','63','--triangulate-initial','--disconnect-graph')
 assert bad['graph_components']==[16,16]
 assert bad['heldout_after']['mean_px']<bad['heldout_before']['mean_px']
 assert bad['pose_after']['position_rms']>bad['pose_before']['position_rms']
 print('PASS observable 360 BA and disconnected low-reprojection counterexample')
