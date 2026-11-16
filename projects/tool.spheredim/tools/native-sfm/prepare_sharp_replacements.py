#!/usr/bin/env python3
"""Prepare native 2048 observations with the dense baseline's 1024 processing."""
import argparse, hashlib, json
from pathlib import Path
import cv2
import numpy as np
import prepare_rig as rig


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for data in iter(lambda:f.read(1024*1024),b''):h.update(data)
    return h.hexdigest()


def process(image, support, operator):
    if image is None or support is None or operator is None or image.shape!=(1024,2048,3) or support.shape!=(1024,2048) or operator.shape!=(512,1024):raise ValueError('Unexpected physical observation dimensions')
    if not np.isin(support,[0,255]).all() or not np.isin(operator,[0,255]).all():raise ValueError('Masks must be binary')
    native=support==255;op=operator==255;support_keep=native.reshape(512,2,1024,2).all(axis=(1,3));keep=support_keep&op
    image=cv2.resize(image,(1024,512),interpolation=cv2.INTER_AREA);image[~keep]=0;guard=rig.feature_guard(keep,16)
    return image,support_keep,op,keep,guard


def validate_mask_source(masks,selection,selection_report):
    if masks['source_report_sha256']!=sha(selection_report):raise ValueError('Operator mask selection report hash differs')
    by={x['frame']:x for x in masks['frames']}
    for row in selection['results']:
        selected=next(c for c in row['candidates'] if c['frame']==row['selected_frame']);entry=by[row['selected_frame']]
        if entry['anchor']!=row['requested_frame'] or entry['mask_brackets']!=selected['mask_brackets']:raise ValueError('Selected anchor or operator mask brackets differ')


def prepare(native_manifest,mask_manifest,selection_report,baseline,output):
    native_manifest,mask_manifest,selection_report,baseline=(Path(x).resolve(strict=True) for x in (native_manifest,mask_manifest,selection_report,baseline));output=Path(output).resolve()
    native=json.loads(native_manifest.read_text());masks=json.loads(mask_manifest.read_text());selection=json.loads(selection_report.read_text());old=json.loads((baseline/'manifest.json').read_text());by={x['frame']:x for x in masks['frames']};selected={r['selected_frame']:next(c for c in r['candidates'] if c['frame']==r['selected_frame']) for r in selection['results']};frames=native['frames']
    validate_mask_source(masks,selection,selection_report)
    if len(selected)!=len(selection['results']) or len({x['frame'] for x in frames})!=len(frames) or native['source_sha256']!=selection['source_sha256'] or {x['frame'] for x in frames}!=set(selected):raise ValueError('Original source or selected inventory mismatch')
    baseline_control=[x for x in old['frames'] if x['source_frame']==1350]
    if len(baseline_control)!=1 or 1350 not in selected or by[1350]['anchor']!=1350:raise ValueError('Missing unchanged frame 1350 control')
    if native['width']!=2048 or native['height']!=1024 or len(by)!=len(frames) or {x['frame'] for x in frames}!=set(by):raise ValueError('Native and propagated frame inventories differ')
    if output.exists():raise FileExistsError(output)
    output.mkdir();(output/'INCOMPLETE').write_text('Preparation not complete\n');rows=[];control=[]
    for row in frames:
        n=row['frame'];entry=by[n]
        if row['timestamp_microseconds']!=entry['timestamp_microseconds'] or row['timestamp_microseconds']!=selected[n]['timestamp_microseconds']:raise ValueError('Timestamp mismatch')
        original=next(r for r in selection['results'] if r['selected_frame']==n)
        if entry['anchor']!=original['requested_frame'] or entry['mask_brackets']!=selected[n]['mask_brackets']:raise ValueError('Selected anchor or operator mask brackets differ')
        operator_path=Path(entry['masks']['operator-keep']['path'])
        if sha(operator_path)!=entry['masks']['operator-keep']['sha256']:raise ValueError('Operator mask hash mismatch')
        operator=cv2.imread(str(operator_path),cv2.IMREAD_GRAYSCALE);rec={'source_frame':n,'timestamp_microseconds':row['timestamp_microseconds'],'anchor':entry['anchor'],'source_packet_pts':selected[n]['source_packet_pts'],'mask_brackets':entry['mask_brackets'],'lenses':{}}
        for i,lens in enumerate(('cam0','cam1')):
            img_path=Path(row[f'lens{i}']);support_path=Path(row[f'mask{i}'])
            if sha(img_path)!=row[f'lens{i}_sha256'] or sha(support_path)!=row[f'mask{i}_sha256']:raise ValueError('Native output hash mismatch')
            image,support,op,keep,guard=process(cv2.imread(str(img_path),cv2.IMREAD_COLOR),cv2.imread(str(support_path),cv2.IMREAD_GRAYSCALE),operator)
            info={}
            for name,value in (('images',image),('lens-support',support),('operator-keep',op),('masks',keep),('feature-masks',guard)):
                dst=output/name/lens/f'frame_{n:06d}.png';dst.parent.mkdir(parents=True,exist_ok=True);value=value if name=='images' else value.astype(np.uint8)*255
                if not cv2.imwrite(str(dst),value):raise OSError(f'Cannot write {dst}')
                info[name]={'path':str(dst),'sha256':sha(dst)}
            rec['lenses'][lens]=info
            if n==1350:
                old_image_path=baseline/'images'/lens/f'frame_{n:06d}.png';old_mask_path=baseline/'masks'/lens/f'frame_{n:06d}.png';expected=baseline_control[0]['lenses'][lens]
                if sha(old_image_path)!=expected['image_sha256'] or sha(old_mask_path)!=expected['mask_sha256']:raise ValueError('Baseline control hash mismatch')
                old_image=cv2.imread(str(old_image_path));old_mask=cv2.imread(str(old_mask_path),0)
                if old_image is None or old_mask is None or old_image.shape!=image.shape or old_mask.shape!=keep.shape:raise ValueError('Missing unchanged baseline control')
                common=keep&(old_mask==255);diff=np.abs(image.astype(np.int16)-old_image.astype(np.int16));control.append({'lens':lens,'mask_changed_pixels':int(np.count_nonzero(keep!=(old_mask==255))),'common_valid_pixels':int(common.sum()),'rgb_changed_pixels_on_common':int(np.count_nonzero(np.any(diff!=0,axis=2)&common)),'rgb_mean_absolute_difference_on_common':float(diff[common].mean()) if common.any() else None,'rgb_max_absolute_difference_on_common':int(diff[common].max()) if common.any() else None})
        rows.append(rec)
    if len(control)!=2 or {x['lens'] for x in control}!={'cam0','cam1'}:raise ValueError('Incomplete unchanged control')
    report={'native_manifest_sha256':sha(native_manifest),'propagated_mask_manifest_sha256':sha(mask_manifest),'selection_report_sha256':sha(selection_report),'baseline_manifest_sha256':sha(baseline/'manifest.json'),'method':'Native 2048 area-reduced to 1024, all four support samples required, intersect propagated operator keep, black invalid RGB, periodic 16-pixel feature guard. Propagated operator masks are not independently reviewed.','frames':rows,'unchanged_frame_1350_control':control};(output/'manifest.json').write_text(json.dumps(report,indent=2)+'\n');(output/'INCOMPLETE').unlink();return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('native_manifest','mask_manifest','selection_report','baseline','output'):p.add_argument(name,type=Path)
    a=p.parse_args();r=prepare(a.native_manifest,a.mask_manifest,a.selection_report,a.baseline,a.output);print(json.dumps({'frames':len(r['frames']),'control':r['unchanged_frame_1350_control']},indent=2))
if __name__=='__main__':main()
