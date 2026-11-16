#!/usr/bin/env python3
"""Score real source-frame windows with bounded paired-observation streaming."""
import argparse, bisect, csv, hashlib, importlib.util, json
from decimal import Decimal
from pathlib import Path
import select_sharp_frames as sharp
import prepare_dense_rig as dense
import stream_sharp_frames as stream


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for data in iter(lambda:f.read(1024*1024),b''):h.update(data)
    return h.hexdigest()


def prepare(source,review_path,fused_path,targets,radius):
    source,review_path,fused_path=(Path(x).resolve(strict=True) for x in (source,review_path,fused_path))
    review=json.loads(review_path.read_text());reviewed=sorted(review['frames'],key=lambda x:x['source_frame']);keys=[x['source_frame'] for x in reviewed]
    if review['frame_dimensions']!=[1024,512] or not keys or keys!=sorted(set(keys)):raise ValueError('Invalid reviewed mask inventory')
    with fused_path.open(newline='') as f:rows=list(csv.DictReader(f))
    fused={int(x['frame']):x for x in rows}
    if len(fused)!=len(rows):raise ValueError('Duplicate fused frame')
    groups=sharp.windows(targets,radius,{n for n in fused if keys[0]<=n<=keys[-1]});streams,packets=dense.packet_map(source);results=[];mask_hashes={}
    for target,group in zip(targets,groups):
        candidates=[]
        for n in group:
            row=fused[n];value=Decimal(row['video_pts_s'])*1000000
            if not value.is_finite() or value!=int(value):raise ValueError('Invalid exact frame timestamp')
            us=int(value);pts=sharp.pair_pts(us,streams,packets);i=bisect.bisect_left(keys,n)
            if i<len(keys) and keys[i]==n:before=after=reviewed[i]
            elif i==0 or i==len(keys):raise ValueError(f'No bracketing reviewed masks: {n}')
            else:before,after=reviewed[i-1],reviewed[i]
            for item in (before,after):
                if item['source_frame'] not in fused or abs(float(fused[item['source_frame']]['video_pts_s'])-float(item['video_pts_s']))>1e-5:raise ValueError('Reviewed mask timestamp mismatch')
                path=(review_path.parent/'masks'/item['mask']).resolve(strict=True);mask_hashes[str(path)]=sha(path)
            candidates.append({'frame':n,'timestamp_microseconds':us,'source_packet_pts':pts,'mask_brackets':[before['source_frame'],after['source_frame']]})
        results.append({'requested_frame':target,'candidates':candidates})
    native=importlib.util.find_spec('insta360_rs._native')
    if native is None or not native.origin:raise ValueError('Cannot identify original runtime')
    return {'method':'Paired native source frames, common reviewed masks and existing sharp-frame scorer; no virtual views.','source':str(source),'source_sha256':sha(source),'review_manifest':str(review_path),'review_manifest_sha256':sha(review_path),'fused_csv':str(fused_path),'fused_csv_sha256':sha(fused_path),'native_extension':native.origin,'native_extension_sha256':sha(native.origin),'radius':radius,'score_selector_sha256':sha(Path(sharp.__file__)),'exporter_sha256':sha(Path(sharp.__file__).with_name('export_timestamp_probes.py')),'stream_helper_sha256':sha(Path(stream.__file__)),'selection_helper_sha256':sha(Path(__file__)),'review_mask_sha256':mask_hashes,'results':results}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','review_manifest','fused_csv','output'):p.add_argument(name,type=Path)
    p.add_argument('--targets',type=int,nargs='+',required=True);p.add_argument('--radius',type=int,default=2);p.add_argument('--timeout',type=float,default=300);a=p.parse_args()
    if a.output.exists():raise FileExistsError(a.output)
    plan=a.output.with_name(a.output.name+'.plan.json')
    stream.write_json_bounded(plan,prepare(a.source,a.review_manifest,a.fused_csv,a.targets,a.radius))
    print(json.dumps(stream.pilot(plan,a.output,a.timeout,verify_reference=False),indent=2))
if __name__=='__main__':main()
