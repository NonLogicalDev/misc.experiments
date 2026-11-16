#!/usr/bin/env python3
"""Show actual completed per-camera images for a background preparation job."""
import argparse
import json
from pathlib import Path
import time


def update(scene,images,manifest,label):
    data=json.loads(scene.read_text());source=json.loads(manifest.read_text())
    indices={f"frame_{f['source_frame']:06d}.png" for f in source['frames']}
    done=sum(len(indices & {p.name for p in (images/lens).glob('*.png')}) for lens in ('cam0','cam1'))
    stage={'name':label,'status':'running','current':done,'total':len(indices)*2,'detail':'Background input preparation; the displayed reconstruction is unchanged.'}
    data['stages']=[s for s in data.get('stages',[]) if s.get('name')!=label]+[stage];data['currentActivity']=len(data['stages'])-1
    tmp=scene.with_name('.'+scene.name+'.prep.tmp');tmp.write_text(json.dumps(data,indent=2)+'\n');tmp.replace(scene)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('scene',type=Path);p.add_argument('images',type=Path);p.add_argument('manifest',type=Path);p.add_argument('--label',required=True);a=p.parse_args()
    while True:
        try:update(a.scene,a.images,a.manifest,a.label)
        except (OSError,ValueError,KeyError,json.JSONDecodeError):pass
        time.sleep(2)
if __name__=='__main__':main()
