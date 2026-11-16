#!/usr/bin/env python3
"""Relay native SfM progress into an existing live activity file without changing artifacts."""
import argparse
import json
import os
from pathlib import Path
import struct
import time

NAMES=('Extracting features','Matching image pairs','Mapping cameras','Merging models','Orienting model','Finishing','Loading','Selecting pairs','Seeding','Refining','Calibrating','Initializing')

def read(path):
    raw=path.read_bytes()
    if len(raw)!=struct.calcsize('<4sIII6qd'):raise ValueError('incomplete status')
    magic,version,index,flags,done,total,*_=struct.unpack('<4sIII6qd',raw)
    if magic!=b'VKPS' or version!=1 or index>=len(NAMES):raise ValueError('unsupported status')
    return index,flags,done,total

def update(activity,workspace,label):
    index,flags,done,total=read(workspace/'progress/status.bin')
    state=json.loads(activity.read_text())
    status='partial' if flags&2 else 'complete' if flags&1 else 'running'
    stage={'name':label+' · '+NAMES[index],'status':status,'detail':'Diagnostic reconstruction; prior splat remains displayed.'}
    if total>0 and done>=0:stage.update(current=done,total=total)
    state['stages']=[stage];state['currentActivity']=0
    state['logs']=[{'name':label,'file':os.path.relpath(workspace/'run.log',activity.parent)}]+[x for x in state.get('logs',[]) if x.get('name') not in ('Baseline SfM','Dense SfM')]
    tmp=activity.with_name('.'+activity.name+'.relay.tmp');tmp.write_text(json.dumps(state,indent=2)+'\n');tmp.replace(activity)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('activity',type=Path);p.add_argument('baseline',type=Path);p.add_argument('dense',type=Path);a=p.parse_args()
    while True:
        workspace,label=(a.dense,'Dense SfM') if (a.dense/'progress/status.bin').exists() else (a.baseline,'Baseline SfM')
        try:update(a.activity,workspace,label)
        except (OSError,ValueError,KeyError,json.JSONDecodeError):pass
        time.sleep(2)
if __name__=='__main__':main()
