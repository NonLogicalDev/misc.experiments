#!/usr/bin/env python3
"""Audit multiple ERP rig models on identical held-out observations."""
import argparse
import csv
import hashlib
import json
import math
import struct
from pathlib import Path
import numpy as np
import compare_rigs as c

BODY_FROM_CV=np.array([[0.,0.,-1.],[1.,0.,0.],[0.,-1.,0.]])


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def match_sections(path):
    data=path.read_bytes();offset=0
    def take(n):
        nonlocal offset
        if n<0 or offset+n>len(data):raise ValueError('Truncated match file')
        chunk=data[offset:offset+n];offset+=n;return chunk
    def u32():return struct.unpack('<I',take(4))[0]
    if take(4)!=b'VKMT' or u32()!=5:raise ValueError('Expected Spirula VKMT v5')
    nimages=u32()
    for _ in range(nimages):take(u32());take(4)
    npairs=u32()
    for _ in range(npairs):take(12);take(u32()*8)
    records_end=offset;ncam=u32()
    for _ in range(ncam):
        take(25);nparams=u32()
        if nparams>16:raise ValueError('Invalid camera parameter count')
        take(nparams*8)
    if ncam:
        nid=u32()
        if nid!=nimages:raise ValueError('Invalid camera index count')
        take(nid*4);take(ncam)
    camera_end=offset;has_cal=take(1)[0]
    if has_cal not in (0,1):raise ValueError('Invalid sensor calibration marker')
    sample_count=u32() if has_cal else None
    if has_cal:take(sample_count*80);take(8)
    if offset!=len(data):raise ValueError('Unexpected match file tail')
    return {'image_and_match_records_sha256':hashlib.sha256(data[:records_end]).hexdigest(),
            'camera_metadata_sha256':hashlib.sha256(data[records_end:camera_end]).hexdigest(),
            'sensor_calibration_sample_present':bool(has_cal),'sensor_rotation_pair_samples':sample_count,
            'images':nimages,'pairs':npairs}


def angular_degrees(R):
    return math.degrees(math.acos(float(np.clip((np.trace(R)-1)/2,-1,1))))


def common_scores(track,poses,width,height):
    common=sorted([o for o in track if all(o[0] in model for model in poses.values())],key=lambda o:(o[1],o[0]))
    scores={name:c.score_track(common,model,width,height) for name,model in poses.items()}
    return common,scores,all(reason is None for _,reason in scores.values())


def calculate(tracks,models,width,height,fused):
    names=list(models);poses={n:c.read_poses(p/'sparse/0') for n,p in models.items()};raw={n:[] for n in names};raw_fail={n:{} for n in names};shared={n:[] for n in names};per_frame={n:{} for n in names};track_rows=[];common_count=0;common_failures={n:{} for n in names}
    for index,track in enumerate(tracks):
        common,scores,all_valid=common_scores(track,poses,width,height);row={'track':index,'original_observations':track,'common_observations':common,'raw':{},'common':{}}
        for n in names:
            values,reason=c.score_track(track,poses[n],width,height)
            row['raw'][n]={'errors':values,'failure':reason}
            if reason:raw_fail[n][reason]=raw_fail[n].get(reason,0)+1
            else:raw[n].extend(values)
            values,reason=scores[n]
            row['common'][n]={'errors':values,'failure':reason}
            if reason:common_failures[n][reason]=common_failures[n].get(reason,0)+1
        if all_valid:
            common_count+=1
            for n in names:
                errors=row['common'][n]['errors'];shared[n].extend(errors)
                for o,error in zip(common[1:-1],errors):per_frame[n].setdefault(o[0],[]).append(error)
            row['included_in_common_all_models']=True
        else:row['included_in_common_all_models']=False
        track_rows.append(row)
    def angle_pair(n,a,b):
        akey=f'cam0/frame_{a:06}.png';bkey=f'cam0/frame_{b:06}.png'
        if akey not in poses[n] or bkey not in poses[n]:return {'missing': [x for x in (akey,bkey) if x not in poses[n]]}
        Ra=poses[n][akey][0].T;Rb=poses[n][bkey][0].T;delta=Ra.T@Rb
        ia,ib=fused[a],fused[b];q0=c.rotation([float(ia[k]) for k in ('q_w','q_x','q_y','q_z')]);q1=c.rotation([float(ib[k]) for k in ('q_w','q_x','q_y','q_z')]);gyro=q0.T@q1;gyro_cv=BODY_FROM_CV.T@gyro@BODY_FROM_CV
        return {'model_rotation_degrees':angular_degrees(delta),'fused_rotation_degrees':angular_degrees(gyro),'difference_degrees':angular_degrees(delta.T@gyro_cv)}
    gyro={n:{f'{a}-{b}':angle_pair(n,a,b) for a,b in ((870,885),(885,900),(900,915),(915,930),(930,945),(945,960))} for n in names}
    all_names=set().union(*(set(p) for p in poses.values()));inventory={}
    for n,p in models.items():
        feature=p/'features';files=sorted(v for v in feature.rglob('*') if v.is_file());log=p/'run.log'
        evidence=[line for line in log.read_text(errors='replace').splitlines() if line.startswith('[match]   Sensor priors:') or line.startswith('[orient]')] if log.exists() else []
        inventory[n]={'sensor_prior_and_orientation_log_lines':evidence,'run_log_sha256':digest(log) if log.exists() else None,'registered_images':len(poses[n]),'missing_images':sorted(all_names-set(poses[n])),'features':{str(v.relative_to(feature)):digest(v) for v in files},'matches_sha256':digest(p/'matches.bin'),'match_sections':match_sections(p/'matches.bin'),'images_sha256':digest(p/'sparse/0/images.bin'),'rig':c.rig_stats(poses[n])}
    return {'input_track_count':len(tracks),'common_valid_track_count':common_count,'common_residual_count':len(shared[names[0]]),'models':{n:{'raw':c.summary(raw[n]),'raw_failures':raw_fail[n],'common_all_models':c.summary(shared[n]),'common_failures':common_failures[n],'common_by_image':{key:c.summary(value) for key,value in per_frame[n].items()},**inventory[n]} for n in names},'gyro':gyro,'track_audit':track_rows}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('tracks',type=Path);p.add_argument('fused_csv',type=Path);p.add_argument('output',type=Path);p.add_argument('--model',action='append',required=True,help='name=run-directory containing features, matches.bin, sparse/0');a=p.parse_args()
    models={}
    for item in a.model:
        name,sep,path=item.partition('=')
        if not sep or not name or name in models:raise ValueError('Models need unique name=path pairs')
        models[name]=Path(path).resolve(strict=True)
    if len(models)<2:raise ValueError('At least two models are required')
    src=json.loads(a.tracks.read_text());data=src['track_observations'];height,width=src['image_shape']
    with a.fused_csv.open(newline='') as f:rows=list(csv.DictReader(f))
    fused={int(row['frame']):row for row in rows}
    if len(rows)!=len(fused):raise ValueError('Duplicate fused frame')
    report={'method':'For each original track retain observations present in all models; identical earliest/latest common observations define endpoints; keep a track in the common comparison only when positive, nondegenerate triangulation succeeds in all models. Raw results and all exclusions remain separately recorded.','units':'angular ERP-equivalent pixels at width 1024; fused orientation is an estimate','audit_script_sha256':digest(Path(__file__)),'tracks_sha256':digest(a.tracks),'evaluator_sha256':digest(Path(c.__file__)),'fused_csv_sha256':digest(a.fused_csv),'model_directories':{n:str(p) for n,p in models.items()},**calculate(data,models,width,height,fused)}
    with a.output.open('x') as f:json.dump(report,f,indent=2,allow_nan=False);f.write('\n')
if __name__=='__main__':main()
