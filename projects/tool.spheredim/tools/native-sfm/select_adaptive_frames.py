#!/usr/bin/env python3
"""Prototype sequential selection over existing masked physical-lens ERP frames."""
import argparse
from fractions import Fraction
from collections import OrderedDict
import json
from pathlib import Path
import time

import cv2
import numpy as np
from scipy.spatial.transform import Rotation
import prepare_rig as rig
import select_sharp_frames as sharp


def bearings(xy, width, height):
    lon=xy[:,0]*(2*np.pi/width);lat=np.pi/2-xy[:,1]*(np.pi/height)
    return np.column_stack((np.cos(lat)*np.cos(lon),-np.cos(lat)*np.sin(lon),np.sin(lat)))


def residual_degrees(points_a,points_b,world_a,world_b,width=1024,height=512):
    a=bearings(points_a,width,height)@world_a.T;b=bearings(points_b,width,height)@world_b.T
    return np.degrees(np.arccos(np.clip(np.sum(a*b,axis=1),-1,1)))


def matched_novelty(a,b,world_a,world_b,sfm_a=None,sfm_b=None):
    if a[1] is None or b[1] is None or len(a[1])<2 or len(b[1])<2:
        return {'status':'insufficient_overlap','matches':0,'reference_cells':0,'candidate_cells':0}
    matcher=cv2.BFMatcher(cv2.NORM_L2)
    def ratios(left,right):
        pairs=matcher.knnMatch(left,right,k=2)
        return {p[0].queryIdx:p[0].trainIdx for p in pairs if len(p)==2 and p[0].distance < .75*p[1].distance}
    forward=ratios(a[1],b[1]);back=ratios(b[1],a[1])
    matches=[(i,j) for i,j in forward.items() if back.get(j)==i]
    pa=np.asarray([a[0][i] for i,j in matches],dtype=float).reshape(-1,2)
    pb=np.asarray([b[0][j] for i,j in matches],dtype=float).reshape(-1,2)
    cells=len({(int(x//256),int(y//128)) for x,y in pa})
    candidate_cells=len({(int(x//256),int(y//128)) for x,y in pb})
    if len(matches)<20 or cells<4 or candidate_cells<4: return {'status':'insufficient_overlap','matches':len(matches),'reference_cells':cells,'candidate_cells':candidate_cells}
    residual=residual_degrees(pa,pb,world_a,world_b)
    result={'status':'ok','matches':len(matches),'reference_cells':cells,'candidate_cells':candidate_cells,'median_degrees':float(np.median(residual)),'raw_median_degrees':float(np.median(residual_degrees(pa,pb,np.eye(3),np.eye(3))))}
    if sfm_a is not None and sfm_b is not None:
        result['sfm_rotation_compensated_median_degrees']=float(np.median(residual_degrees(pa,pb,sfm_a,sfm_b)))
        relative_gyro=world_a.T@world_b;relative_sfm=sfm_a.T@sfm_b
        result['fused_sfm_relative_rotation_difference_degrees']=float(Rotation.from_matrix(relative_gyro.T@relative_sfm).magnitude()*180/np.pi)
    return result


def exposure_normalize(image,valid):
    values=image[valid]
    if len(values)<1024: raise ValueError('Insufficient valid scene pixels')
    lo,hi=np.percentile(values,[5,95])
    if hi-lo<10: raise ValueError('Insufficient scene contrast')
    return np.clip((image.astype(np.float32)-lo)*(255/(hi-lo)),0,255).astype(np.uint8)


def scene_or_unknown(image, mask):
    """Exclude a lens when valid support or contrast cannot support measurement."""
    try:
        return exposure_normalize(image,mask),mask
    except ValueError as exc:
        if str(exc) not in ('Insufficient valid scene pixels','Insufficient scene contrast'): raise
        return np.zeros_like(image),np.zeros_like(mask)


def quality_gate(values, maxima, matches):
    measurable=[k for k in range(2) if maxima[k] is not None and values[k] is not None]
    overlap_measurable=[k for k in measurable if matches[k]['status']=='ok']
    eligible=bool(overlap_measurable)
    normalized=min(values[k]/maxima[k] for k in measurable) if measurable else None
    low=any(values[k]<.75*maxima[k] for k in measurable) if measurable else None
    return eligible, normalized, low


def elapsed_seconds(reference_us, candidate_us):
    if candidate_us <= reference_us: raise ValueError('Candidate must follow reference')
    return (candidate_us-reference_us)/1000000


def rank_components(sharpness, novelty, elapsed):
    novelty_score=float(1-np.exp(-novelty/.5)) if novelty is not None else None
    penalty=float(.15*np.exp(-elapsed))
    total=sharpness*novelty_score-penalty if sharpness is not None and novelty_score is not None else None
    return novelty_score,penalty,total


def score_batch(candidates, items, reference):
    """Freeze quality against this nearby batch; later batches cannot revise it."""
    scores=[]; maxima=[]
    for lens in range(2):
        valid=[j for j,item in enumerate(items) if np.count_nonzero(item['masks'][lens])>=1024]
        by_candidate=[None]*len(items)
        if not valid or np.count_nonzero(reference['masks'][lens])<1024:
            scores.append(by_candidate);maxima.append(None);continue
        compared=[items[j] for j in valid]+[reference]
        try:
            values=sharp.score_window([x['images'][lens] for x in compared],[x['masks'][lens] for x in compared],0)
            for j,value in zip(valid,values): by_candidate[j]=value['score']
            scores.append(by_candidate);maxima.append(max(x['score'] for x in values))
        except ValueError as exc:
            if str(exc)!='Insufficient valid textured tiles': raise
            scores.append(by_candidate);maxima.append(None)
    for j,c in enumerate(candidates):
        c['sharpness']=[scores[k][j] for k in range(2)]
        c['quality_batch']={'first_frame':candidates[0]['frame'],'last_frame':candidates[-1]['frame'],'includes_reference':True,'lens_maxima':maxima}
        c['quality_eligible'],c['sharpness_normalized'],c['relative_low_sharpness']=quality_gate(c['sharpness'],maxima,c['matches'])
        c['novelty_normalized'],c['age_penalty'],c['total_score']=rank_components(c['sharpness_normalized'],c['novelty_degrees'],c['elapsed_seconds_from_reference'])


def choose(candidates, max_gap):
    # A qualifying batch returns immediately, so later batches cannot compete with it.
    eligible=[c for c in candidates if c['quality_eligible'] and c['novelty_degrees'] is not None and c['novelty_degrees']>=.5]
    if eligible: return max(eligible,key=lambda c:(c['total_score'],-c['step'])), 'novel_and_measurable'
    if not max_gap: return None,None
    overlap=[c for c in candidates if c['quality_eligible'] and c['novelty_degrees'] is not None]
    if overlap: return max(overlap,key=lambda c:(c['novelty_degrees'],-c['step'])), 'max_gap_overlap_fallback'
    return None, 'max_gap_insufficient_measurable_overlap'


def coverage(poses, frames, chosen):
    data=json.loads(Path(poses).read_text())['frames'];lookup={int(v['source_frame']):np.asarray(v['world_from_camera'],float)[:3,3] for v in data}
    ids=[f['source_frame'] for f in frames]
    if any(n not in lookup or not np.isfinite(lookup[n]).all() for n in ids): raise ValueError('Missing or invalid preliminary position')
    points=np.stack([lookup[n] for n in ids]); selected=np.stack([lookup[n] for n in chosen])
    uniform=points[np.linspace(0,len(points)-1,len(chosen)).round().astype(int)]
    def stats(anchors):
        distance=np.linalg.norm(points[:,None,:]-anchors[None,:,:],axis=2).min(axis=1)
        return {'median':float(np.median(distance)),'p95':float(np.percentile(distance,95)),'max':float(distance.max())}
    return {'method':'Nearest preliminary cam0 centers in arbitrary scene units; position is not scene visibility or independent pose truth.','adaptive':stats(selected),'uniform_time_same_count':stats(uniform)}


def validate_timestamp(frame):
    row=frame['fused_row'];us=frame['timestamp_microseconds']
    if int(row['frame'])!=frame['source_frame'] or abs(float(row['video_pts_s'])*1000000-us)>1: raise ValueError('Fused frame or timestamp mismatch')
    packets=frame['source_packet_pts']
    times=[Fraction(p['pts'])*Fraction(p['time_base']) for p in packets]
    if len(times)!=2 or len({p['stream'] for p in packets})!=2 or times[0]!=times[1] or abs(times[0]-Fraction(us,1000000))>Fraction(1,1000000): raise ValueError('Physical pair timestamp mismatch')


def run(dataset,poses,output,limit,timeout,window=6):
    if window not in (2,3,6) or (limit is not None and limit<2) or not np.isfinite(timeout) or timeout<=0: raise ValueError('Invalid window, frame limit or timeout')
    dataset=Path(dataset).resolve(strict=True);poses=Path(poses).resolve(strict=True);output=Path(output).resolve()
    if output.exists(): raise FileExistsError(output)
    manifest=json.loads((dataset/'manifest.json').read_text()); frames=manifest['frames'][:limit]
    source_manifest=Path(manifest['source_manifest']).resolve(strict=True)
    if rig.sha(source_manifest)!=manifest['source_manifest_sha256']: raise ValueError('Source manifest hash mismatch')
    provenance=json.loads(source_manifest.read_text());source=Path(provenance['source']).resolve(strict=True)
    if rig.sha(source)!=provenance['source_sha256']: raise ValueError('Recording source hash mismatch')
    ids=[x['source_frame'] for x in frames]; timestamps=[x['timestamp_microseconds'] for x in frames]
    if len(frames)<2 or ids!=sorted(set(ids)) or timestamps!=sorted(set(timestamps)): raise ValueError('Invalid source frame order or timestamps')
    if manifest['resolution']!=[1024,512]: raise ValueError('Expected native 1024x512 ERP inputs')
    for f in frames:
        validate_timestamp(f)
    rig_config=json.loads((dataset/'rig-metadata.json').read_text())
    members={x['prefix']:x for x in rig_config['rigs'][0]['members']}
    if set(members)!={'cam0','cam1'}: raise ValueError('Invalid rig metadata')
    corrections=[]
    for lens in ('cam0','cam1'):
        w,x,y,z=members[lens]['rotation']; rotation=Rotation.from_quat([x,y,z,w]).as_matrix()
        corrections.append(rig.BODY_FROM_CV@rotation.T@rig.BODY_FROM_CV.T)
    pose_rows=json.loads(poses.read_text())['frames']; sfm={int(x['source_frame']):np.asarray(x['world_from_camera'],float)[:3,:3]@rig.BODY_FROM_CV.T for x in pose_rows}
    cache=OrderedDict(); sift=cv2.SIFT_create(nfeatures=1000); start=time.monotonic()
    def load(i):
        if time.monotonic()-start>timeout: raise TimeoutError('CPU prototype exceeded time limit')
        if i in cache: cache.move_to_end(i);return cache[i]
        f=frames[i];images=[]; masks=[];features=[]
        for lens in ('cam0','cam1'):
            name=f"frame_{f['source_frame']:06d}.png"; ip=dataset/'images'/lens/name;mp=dataset/'feature-masks'/lens/name
            meta=f['lenses'][lens]
            if rig.sha(ip)!=meta['image_sha256'] or rig.sha(mp)!=meta['feature_mask_sha256']:raise ValueError('Image or mask hash mismatch')
            image=cv2.imread(str(ip),cv2.IMREAD_GRAYSCALE); mask=cv2.imread(str(mp),cv2.IMREAD_GRAYSCALE)
            if image is None or mask is None or image.shape!=(512,1024) or mask.shape!=image.shape:raise ValueError('Missing image or mask')
            mask=cv2.erode((mask==255).astype(np.uint8),np.ones((17,17),np.uint8),borderType=cv2.BORDER_CONSTANT,borderValue=0)>0
            normalized,mask=scene_or_unknown(image,mask)
            kp,desc=sift.detectAndCompute(normalized,mask.astype(np.uint8)*255)
            valid=[j for j,k in enumerate(kp) if k.size<=16]
            features.append((np.asarray([kp[j].pt for j in valid]),desc[valid] if desc is not None and valid else None));images.append(normalized);masks.append(mask)
        q=f['fused_row'];world=Rotation.from_quat([float(q[k]) for k in ('q_x','q_y','q_z','q_w')]).as_matrix()
        item={'images':images,'masks':masks,'features':features,'world':[world@c for c in corrections],'sfm':sfm.get(f['source_frame'])};cache[i]=item
        while len(cache)>21:cache.popitem(last=False)
        return item
    selected=[0];decisions=[]; cursor=0
    while cursor<len(frames)-1:
        ref=load(cursor); candidates=[];chosen=None;reason=None
        for end in sorted({min(cursor+step,len(frames)-1) for step in range(window,18,window)} | {min(cursor+18,len(frames)-1)}):
            start_idx=cursor+1 if not candidates else candidates[-1]['index']+1
            batch_start=len(candidates)
            for i in range(start_idx,end+1):
                item=load(i); per=[matched_novelty(ref['features'][j],item['features'][j],ref['world'][j],item['world'][j],ref['sfm'] if j==0 else None,item['sfm'] if j==0 else None) for j in range(2)]
                valid=[x['median_degrees'] for x in per if x['status']=='ok']
                candidates.append({'index':i,'step':i-cursor,'frame':ids[i],'timestamp_microseconds':timestamps[i],'elapsed_seconds_from_reference':elapsed_seconds(timestamps[cursor],timestamps[i]),'matches':per,'novelty_degrees':float(np.median(valid)) if valid else None})
            batch=candidates[batch_start:]
            score_batch(batch,[load(c['index']) for c in batch],ref)
            terminal=end==min(cursor+18,len(frames)-1)
            chosen,reason=choose(candidates,terminal)
            if chosen or terminal: break
        if not chosen:
            decisions.append({'reference_frame':ids[cursor],'selected_frame':None,'reason':reason,'examined':candidates})
            break
        decisions.append({'reference_frame':ids[cursor],'selected_frame':chosen['frame'],'reason':reason,'examined':candidates})
        cursor=chosen['index'];selected.append(cursor)
    chosen=[ids[i] for i in selected]
    gaps=np.diff([timestamps[i] for i in selected])/1e6
    report={'method':'Sequential forward scan of existing paired native ERP observations; SIFT mutual ratio matches with fused world-from-body and fixed lens rotation compensation, following export_rotation_priors.py. Preliminary SfM comparison is not independent of its orientation prior. Bearing coordinates follow the pinned SfM feature convention without a +0.5 pixel shift; the underlying pixel convention remains unverified. Novelty is angular bearing displacement, not proof of translation or coverage. Unknown overlap is never classified as novelty. Textureless lens sharpness is unknown; at least one measurable lens must have overlap. Relative sharpness is a soft ranking factor, not a blur classifier. Exposure normalization and masks reduce but do not eliminate confounds; no virtual views or new poses.','config':{'window_steps':window,'max_gap_steps':18,'minimum_step':1,'age_penalty_weight':.15,'age_tau_seconds':1.0,'novelty_scale_degrees':.5,'ratio':.75,'minimum_matches_one_lens':20,'minimum_cells_one_lens':4,'grid':[4,4],'novelty_degrees':.5,'relative_low_sharpness_fraction_of_batch_best':.75,'require_measurable_lens_with_overlap':True,'feature_type':'SIFT, up to 1000, size <=16','feature_mask_extra_erosion':8,'cache_max_frames':21,'time_limit_seconds':timeout},'dataset':str(dataset),'recording':str(source),'recording_sha256':provenance['source_sha256'],'source_manifest_sha256':rig.sha(source_manifest),'dataset_manifest_sha256':rig.sha(dataset/'manifest.json'),'rig_metadata_sha256':rig.sha(dataset/'rig-metadata.json'),'poses_sha256':rig.sha(poses),'script_sha256':rig.sha(Path(__file__)),'selected_indices':chosen,'selected_timestamps_microseconds':[timestamps[i] for i in selected],'selection_count':len(selected),'complete':cursor==len(frames)-1,'processed_frame_count':len(frames),'temporal_gaps_seconds':{'median':float(np.median(gaps)) if len(gaps) else None,'max':float(np.max(gaps)) if len(gaps) else None},'coverage_full_trajectory':coverage(poses,frames,chosen),'coverage_processed_prefix':coverage(poses,frames[:selected[-1]+1],chosen),'elapsed_seconds':time.monotonic()-start,'decisions':decisions}
    raw=(json.dumps(report,indent=2,allow_nan=False)+'\n').encode()
    if len(raw)>5*1024**2: raise RuntimeError('Report exceeds 5 MiB')
    output.write_bytes(raw);return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('dataset',type=Path);p.add_argument('poses',type=Path);p.add_argument('output',type=Path);p.add_argument('--limit',type=int);p.add_argument('--timeout',type=float,default=300);p.add_argument('--window',type=int,choices=(2,3,6),default=6)
    a=p.parse_args()
    if (a.limit is not None and a.limit<2) or a.timeout<=0: p.error('limit >= 2 and timeout > 0 required')
    run(a.dataset,a.poses,a.output,a.limit,a.timeout,a.window)


if __name__=='__main__': main()
