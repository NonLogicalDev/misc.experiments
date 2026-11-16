#!/usr/bin/env python3
"""Compare SfM relative rotation to leveled DVO poses and fused heading."""
import argparse
import csv
import json
import math
from pathlib import Path
import numpy as np


def angle(rotation):
    return math.degrees(math.acos(float(np.clip((np.trace(rotation)-1)/2,-1,1))))


def diagnose(frames, dvo, fused, source_frames):
    byframe={f['source_frame']:f for f in frames}
    if len(byframe)!=len(frames): raise ValueError('Duplicate source frame')
    bytime={round(f['time_seconds'],5):f for f in dvo}
    out=[]
    for index in source_frames:
        pos=next(i for i,f in enumerate(frames) if f['source_frame']==index)
        if pos==0 or pos==len(frames)-1:raise ValueError('Target has no neighbors')
        for a,b in ((frames[pos-1],frames[pos]),(frames[pos],frames[pos+1])):
            i,j=a['source_frame'],b['source_frame']; da=bytime[round(a['time_seconds'],5)];db=bytime[round(b['time_seconds'],5)]
            sa=np.array(a['world_from_camera'])[:,:3];sb=np.array(b['world_from_camera'])[:,:3]
            ra=np.array(da['world_from_camera'])[:,:3];rb=np.array(db['world_from_camera'])[:,:3]
            delta_s=sa.T@sb;delta_d=ra.T@rb
            ha=fused[i];hb=fused[j]
            if abs(ha['pts']-a['time_seconds'])>1e-4 or abs(hb['pts']-b['time_seconds'])>1e-4:raise ValueError('Fused frame timestamp mismatch')
            row={'from_frame':i,'to_frame':j,'sfm_relative_degrees':angle(delta_s),'dvo_relative_degrees':angle(delta_d),
                 'sfm_dvo_relative_disagreement_degrees':angle(delta_s.T@delta_d),
                 'sfm_up_change_degrees':math.degrees(math.acos(float(np.clip(sa[:,1]@sb[:,1],-1,1)))),
                 'dvo_up_change_degrees':math.degrees(math.acos(float(np.clip(ra[:,1]@rb[:,1],-1,1)))),
                 'fused_heading_change_degrees':abs(math.degrees(hb['heading']-ha['heading']))}
            if row not in out:out.append(row)
    return out


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('sfm_poses',type=Path);p.add_argument('stabilized_dvo',type=Path);p.add_argument('fused_csv',type=Path);p.add_argument('output',type=Path);p.add_argument('source_frames',type=int,nargs='+');a=p.parse_args()
    fused={}
    with a.fused_csv.open() as f:
        for r in csv.DictReader(f):
            i=int(r['frame'])
            if i in fused:raise ValueError('Duplicate fused frame')
            fused[i]={'pts':float(r['video_pts_s']),'heading':float(r['heading_rad'])}
    rows=diagnose(json.loads(a.sfm_poses.read_text())['frames'],json.loads(a.stabilized_dvo.read_text())['frames'],fused,a.source_frames)
    with a.output.open('x') as f: json.dump(rows,f,indent=2,allow_nan=False);f.write('\n')
if __name__=='__main__':main()
