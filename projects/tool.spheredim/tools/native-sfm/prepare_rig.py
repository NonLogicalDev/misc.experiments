#!/usr/bin/env python3
"""Prepare paired body-oriented spherical lens frames and reviewed mask sidecars."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
from fractions import Fraction
import shutil
import cv2
import numpy as np
from scipy.spatial.transform import Rotation

from camera_basis import BODY_FROM_CV


def rig_extrinsic(rotation,baseline):
    rotation=np.asarray(rotation,dtype=float);baseline=np.asarray(baseline,dtype=float)
    if rotation.shape!=(3,3) or baseline.shape!=(3,) or not np.all(np.isfinite(rotation)) or not np.all(np.isfinite(baseline)) or not np.allclose(rotation.T@rotation,np.eye(3),atol=1e-6) or np.linalg.det(rotation)<.999999 or not np.isclose(np.linalg.norm(baseline),1,atol=1e-6):raise ValueError('Invalid fitted rig rotation or baseline')
    r=BODY_FROM_CV.T@rotation.T@BODY_FROM_CV
    t=-r@BODY_FROM_CV.T@baseline
    return r,t


def body_rays(width,height):
    lon=(np.arange(width,dtype=np.float64)+.5)*(2*np.pi/width)
    lat=np.pi/2-(np.arange(height,dtype=np.float64)+.5)*(np.pi/height)
    c=np.cos(lat)[:,None]
    return np.stack(np.broadcast_arrays(c*np.cos(lon)[None,:],-c*np.sin(lon)[None,:],np.sin(lat)[:,None]),axis=-1)


def keep_sample_all_neighbors(keep,rays):
    h,w=keep.shape;lon=np.mod(np.arctan2(-rays[...,1],rays[...,0]),2*np.pi);lat=np.arcsin(np.clip(rays[...,2],-1,1))
    x=lon*w/(2*np.pi)-.5;y=(np.pi/2-lat)*h/np.pi-.5;x0=np.floor(x).astype(np.int32);y0=np.floor(y).astype(np.int32)
    # All four neighbors, including zero-weight taps, are kept; wrap only longitude.
    within=(y0>=0)&(y0+1<h);ya=np.clip(y0,0,h-1);yb=np.clip(y0+1,0,h-1);xa=x0%w;xb=(x0+1)%w
    return within & keep[ya,xa] & keep[ya,xb] & keep[yb,xa] & keep[yb,xb]


def operator_body_keep(stable_keep,q_stable_to_body):
    h,w=stable_keep.shape;hi=body_rays(w*2,h*2);stable=hi@q_stable_to_body
    fine=keep_sample_all_neighbors(stable_keep,stable)
    return fine.reshape(h,2,w,2).all(axis=(1,3))


def feature_guard(keep,radius):
    if radius==0:return keep.copy()
    # Periodic longitude; outside the poles is invalid rather than reflected.
    pad=np.pad(keep.astype(np.uint8),((0,0),(radius,radius)),mode='wrap')
    pad=np.pad(pad,((radius,radius),(0,0)),mode='constant')
    kernel=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(2*radius+1,2*radius+1))
    return cv2.erode(pad,kernel)[radius:-radius,radius:-radius].astype(bool)


def spatial_feature_split(guarded,tile_size=128,interior=16):
    h,w=guarded.shape;y,x=np.indices((h,w));column=x//tile_size;row=y//tile_size
    held=(column+2*row)%5==0
    inside=(x%tile_size>=interior)&(x%tile_size<tile_size-interior)&(y%tile_size>=interior)&(y%tile_size<tile_size-interior)
    return guarded & ~held,guarded & held & inside


def per_lens_feature_split(guarded,lens,interior=16):
    if guarded.shape!=(512,1024) or lens not in ('cam0','cam1'):raise ValueError('Expected 1024x512 mask and a known lens')
    y,x=np.indices(guarded.shape);left=512 if lens=='cam0' else 768
    held=(x>=left)&(x<left+256)&(y>=256)&(y<512)
    inside=(x>=left+interior)&(x<left+256-interior)&(y>=256+interior)&(y<512-interior)
    return guarded & ~held,guarded & inside


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def manifest_text(R,t):
    q=Rotation.from_matrix(R).as_quat()
    manifest={'image_dir':'images','mask_dir':'masks','cameras':[{'prefix':'cam0','model':'equirectangular'},{'prefix':'cam1','model':'equirectangular'}],
      'rigs':[{'name':'physical-lenses','members':[{'prefix':'cam0','rotation':[1,0,0,0],'translation':[0,0,0],'fixed':True,'refine':'none'},
      {'prefix':'cam1','rotation':[float(q[3]),float(q[0]),float(q[1]),float(q[2])],'translation':np.asarray(t).tolist(),'fixed':True,'refine':'none'}]}]}
    return json.dumps(manifest,indent=2,allow_nan=False)+'\n'


def write_png(path,image):
    if not cv2.imwrite(str(path),image,[cv2.IMWRITE_PNG_COMPRESSION,3]):raise OSError(f'Cannot write {path}')


def validate_frames(frames,reviewed,fused):
    indices=[x['frame'] for x in frames]
    if len(indices)<2 or any(not isinstance(n,int) or isinstance(n,bool) for n in indices) or indices!=sorted(set(indices)):
        raise ValueError('Expected at least two unique, sorted source frames')
    if any(n not in reviewed or n not in fused for n in indices):
        raise ValueError('Missing reviewed mask or fused orientation frame')


def split_features(guarded,lens,split,tile_size):
    if split=='none':return guarded.copy(),np.zeros_like(guarded,dtype=bool)
    if split=='per-lens-blocks':return per_lens_feature_split(guarded,lens)
    if split=='grid':return spatial_feature_split(guarded,tile_size)
    raise ValueError('Invalid spatial split')


def write_sheet_page(output,lens,tiles,page,evaluation=False):
    if not tiles:return
    blank=np.zeros_like(tiles[0]); padded=tiles+[blank]*((-len(tiles))%4)
    sheet=np.concatenate([np.concatenate(padded[i:i+4],axis=1) for i in range(0,len(padded),4)],axis=0)
    suffix='-evaluation-review' if evaluation else '-review'
    write_png(output/f'{lens}{suffix}-{page:03d}.png',sheet)


def prepare(probe_path,review_path,fused_path,rig_path,output,guard=16,tile_size=128,split="grid",max_output_mib=None):
    probe=json.loads(probe_path.read_text());review=json.loads(review_path.read_text());rig=json.loads(rig_path.read_text());frames=probe['frames'];reviewed={x['source_frame']:x for x in review['frames']}
    if len(reviewed)!=len(review['frames']):raise ValueError('Duplicate reviewed source frames')
    if probe['width']!=2048 or probe['height']!=1024 or review['frame_dimensions']!=[1024,512] or not probe['stabilization'].startswith('OFF') or probe['rolling_shutter']!='OFF':raise ValueError('Unexpected projection or stabilization metadata')
    with fused_path.open(newline='') as f:
        rows=list(csv.DictReader(f))
    fused={int(x['frame']):x for x in rows}
    if len(rows)!=len(fused):raise ValueError('Duplicate fused frame indices')
    validate_frames(frames,reviewed,fused)
    R,t=rig_extrinsic(rig['rotation_matrix'],rig['baseline_direction'])
    if guard<0 or guard>64:raise ValueError('Invalid feature guard')
    if tile_size not in (128,256):raise ValueError('Tile size must be 128 or 256')
    if split not in ('grid','per-lens-blocks','none'):raise ValueError('Invalid spatial split')
    if output.exists():raise FileExistsError(output)
    budget=32*1024**2+len(frames)*4*1024**2
    if max_output_mib is not None:
        if max_output_mib<=0:raise ValueError('Output limit must be positive')
        budget=min(budget,max_output_mib*1024**2)
    if shutil.disk_usage(output.parent).free<35*1024**3+budget:raise RuntimeError('Less than 35 GiB reserve plus estimated dataset budget')
    output.mkdir();(output/'INCOMPLETE').write_text('Preparation not yet verified\n')
    for d in ('images','masks','feature-masks','guarded-masks','eval-masks','operator-keep','lens-support'):
        for lens in ('cam0','cam1'):(output/d/lens).mkdir(parents=True)
    records=[];sheets={'cam0':[],'cam1':[]};eval_sheets={'cam0':[],'cam1':[]}
    for frame in frames:
        n=frame['frame'];f=fused[n];r=reviewed[n];pts=frame['timestamp_microseconds']/1e6
        if abs(float(f['video_pts_s'])-pts)>1e-5 or abs(r['video_pts_s']-pts)>1e-5:raise ValueError(f'Frame {n} timestamp mismatch')
        packets=frame['source_packet_pts']
        if sorted(v['stream'] for v in packets)!=[0,1] or any(abs(float(v['pts']*Fraction(v['time_base']))-pts)>1e-6 for v in packets):raise ValueError(f'Frame {n} source stream timestamps differ')
        mask_path=review_path.parent/'masks'/r['mask'];source_review=frame['reviewed_operator_mask']
        if mask_path.resolve()!=Path(source_review['path']).resolve() or sha(mask_path)!=source_review['sha256']:raise ValueError(f'Frame {n} reviewed mask provenance mismatch')
        mask=cv2.imread(str(mask_path),cv2.IMREAD_GRAYSCALE)
        if mask is None or mask.shape!=(512,1024):raise ValueError(f'Frame {n} reviewed mask invalid')
        q=Rotation.from_quat([float(f[x]) for x in ('q_x','q_y','q_z','q_w')]).as_matrix();heading=float(f['heading_rad'])
        if not np.all(np.isfinite(q)) or not np.isfinite(heading):raise ValueError('Invalid fused orientation')
        transform=q.T@Rotation.from_euler('z',heading).as_matrix();op=operator_body_keep(mask==255,transform)
        stem=f'frame_{n:06}.png';item={'source_frame':n,'timestamp_microseconds':frame['timestamp_microseconds'],'source_packet_pts':packets,'review_mask_sha256':sha(mask_path),'fused_row':{k:f[k] for k in ('frame','video_pts_s','q_w','q_x','q_y','q_z','heading_rad')},'lenses':{}}
        for i,lens in enumerate(('cam0','cam1')):
            image_path=Path(frame[f'lens{i}']);support_path=Path(frame[f'mask{i}'])
            if sha(image_path)!=frame[f'lens{i}_sha256'] or sha(support_path)!=frame[f'mask{i}_sha256']:raise ValueError(f'Frame {n} source hash mismatch')
            image=cv2.imread(str(image_path),cv2.IMREAD_COLOR);support=cv2.imread(str(support_path),cv2.IMREAD_GRAYSCALE)
            if image is None or support is None or image.shape!=(1024,2048,3) or support.shape!=(1024,2048):raise ValueError('Input image or mask shape mismatch')
            # 2x2 area downsample; every source support pixel must be white.
            support_keep=(support==255).reshape(512,2,1024,2).all(axis=(1,3));image=cv2.resize(image,(1024,512),interpolation=cv2.INTER_AREA);keep=support_keep&op;guarded=feature_guard(keep,guard);features,evaluation=split_features(guarded,lens,split,tile_size)
            display=image.copy();display[~support_keep]=(display[~support_keep]*.25+np.array([100,0,0])*.75).astype(np.uint8);display[support_keep&~op]=(display[support_keep&~op]*.25+np.array([0,0,255])*.75).astype(np.uint8);display[keep&~guarded]=(display[keep&~guarded]*.5+np.array([0,255,255])*.5).astype(np.uint8)
            image[~keep]=0
            for directory,array in [('images',image),('masks',keep.astype(np.uint8)*255),('feature-masks',features.astype(np.uint8)*255),('guarded-masks',guarded.astype(np.uint8)*255),('eval-masks',evaluation.astype(np.uint8)*255),('operator-keep',op.astype(np.uint8)*255),('lens-support',support_keep.astype(np.uint8)*255)]:write_png(output/directory/lens/stem,array)
            thumb=cv2.resize(display,(512,256),interpolation=cv2.INTER_AREA);cv2.rectangle(thumb,(0,0),(512,25),(0,0,0),-1);cv2.putText(thumb,f'{lens} frame {n}',(4,18),cv2.FONT_HERSHEY_SIMPLEX,.5,(255,255,255),1,cv2.LINE_AA);sheets[lens].append(thumb)
            eval_display=image.copy();eval_display[evaluation]=(eval_display[evaluation]*.25+np.array([0,255,0])*.75).astype(np.uint8);et=cv2.resize(eval_display,(512,256),interpolation=cv2.INTER_AREA);cv2.rectangle(et,(0,0),(512,25),(0,0,0),-1);cv2.putText(et,f'{lens} frame {n} evaluation locations',(4,18),cv2.FONT_HERSHEY_SIMPLEX,.5,(255,255,255),1,cv2.LINE_AA);eval_sheets[lens].append(et)
            item['lenses'][lens]={'image_source_sha256':frame[f'lens{i}_sha256'],'support_source_sha256':frame[f'mask{i}_sha256'],'image_sha256':sha(output/'images'/lens/stem),'mask_sha256':sha(output/'masks'/lens/stem),'feature_mask_sha256':sha(output/'feature-masks'/lens/stem),'valid_fraction':float(keep.mean()),'feature_valid_fraction':float(features.mean()),'evaluation_valid_fraction':float(evaluation.mean()),'evaluation_mask_sha256':sha(output/'eval-masks'/lens/stem)}
        records.append(item)
        if len(sheets['cam0'])==16 or len(records)==len(frames):
            page=(len(records)-1)//16+1
            for lens in ('cam0','cam1'):
                write_sheet_page(output,lens,sheets[lens],page);write_sheet_page(output,lens,eval_sheets[lens],page,True)
                sheets[lens].clear();eval_sheets[lens].clear()
        used=sum(p.stat().st_size for p in output.rglob('*') if p.is_file())
        if used>budget or shutil.disk_usage(output).free<35*1024**3:raise RuntimeError('Dataset exceeded budget or free-space reserve')
    (output/'rig-zero.json').write_text(manifest_text(R,np.zeros(3)));(output/'rig-separated.json').write_text(manifest_text(R,t))
    meta={'status':'prepared; operator and support overlays require review','source_manifest':str(probe_path.resolve()),'source_manifest_sha256':sha(probe_path),'review_manifest_sha256':sha(review_path),'fused_csv_sha256':sha(fused_path),'fit_rig_sha256':sha(rig_path),'pixel_basis':'exporter body ERP and Spirula CV bearing differ by BODY_FROM_CV; exporter samples centers at +0.5 while Spirula bearing consumes feature coordinates without +0.5; feature coordinate convention remains unverified','resolution':[1024,512],'physical_observations_per_frame':2,'source':'nominal body ERP, not virtual perspective or cubemap','image_semantics':'2x2 area downsample, RGB black where support or operator keep fails','mask_semantics':'white keep; 4 source subpixel centers sample all 4 stable-mask neighbors, longitude wrapped, pole exterior invalid; all 4 physical support samples must be white','feature_guard_pixels':guard,'feature_guard_note':'16 pixels at 1024 corresponds to 32 pixels at 2048; separate descriptor guard, not the image blackout mask','estimated_output_budget_bytes':budget,'spatial_split':('No held-out features; every guarded location is available for training and evaluation masks are empty.' if split=='none' else 'Per-lens 256x256 blocks: cam0 x512:768 y256:512, cam1 x768:1024 y256:512; training outside its lens block; evaluation inset 16px; both intersect guarded validity. Keypoint-center split, not descriptor-footprint independence.' if split=='per-lens-blocks' else f'{tile_size}x{tile_size} ERP tiles; heldout if (column+2*row)%5 == 0; training uses guarded valid pixels outside all heldout tiles; evaluation uses guarded valid pixels at least 16px inside heldout tiles; keypoint-center split, not descriptor-footprint independence'),'review_sheet_legend':'blue physical absence, red operator exclusion, yellow feature guard; overlays for review only','rig_rotation_cam1_from_rig':R.tolist(),'rig_translation_cam1_from_rig_unit_baseline':t.tolist(),'baseline_scale':'unit fitted direction; actual metric scale unverified','frames':records}
    (output/'manifest.json').write_text(json.dumps(meta,indent=2)+'\n');(output/'INCOMPLETE').unlink()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('probe_manifest',type=Path);p.add_argument('review_manifest',type=Path);p.add_argument('fused_csv',type=Path);p.add_argument('rig_fit',type=Path);p.add_argument('output',type=Path);p.add_argument('--guard',type=int,default=16);p.add_argument('--tile-size',type=int,choices=(128,256),default=128);p.add_argument('--split',choices=('grid','per-lens-blocks','none'),default='grid');p.add_argument('--max-output-mib',type=int,help='Hard output size limit in MiB');a=p.parse_args();prepare(a.probe_manifest,a.review_manifest,a.fused_csv,a.rig_fit,a.output,a.guard,a.tile_size,a.split,a.max_output_mib)
if __name__=='__main__':main()
