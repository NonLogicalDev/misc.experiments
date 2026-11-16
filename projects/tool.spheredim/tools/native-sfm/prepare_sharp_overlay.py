#!/usr/bin/env python3
"""Prepare a training-only pose/image overlay on a verified dense rig dataset."""
import argparse,copy,hashlib,json,os,tempfile
from fractions import Fraction
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for data in iter(lambda:f.read(1048576),b''):h.update(data)
    return h.hexdigest()


def compose(camera,rig):
    rc=np.asarray(camera['rotation'],dtype=np.float64);tc=np.asarray(camera['translation'],dtype=np.float64);rr=np.asarray(rig['rotation'],dtype=np.float64);tr=np.asarray(rig['translation'],dtype=np.float64)
    for matrix in (rc,rr):
        if matrix.shape!=(3,3) or not np.isfinite(matrix).all() or not np.allclose(matrix@matrix.T,np.eye(3),atol=1e-6) or abs(np.linalg.det(matrix)-1)>1e-6:raise ValueError('Invalid rig rotation')
    if tc.shape!=(3,) or tr.shape!=(3,) or not np.isfinite(tc).all() or not np.isfinite(tr).all():raise ValueError('Invalid rig translation')
    return rc@rr,rc@tr+tc


def check_pts(row):
    packets=row['source_packet_pts'];t=Fraction(row['timestamp_microseconds'],1000000)
    if len(packets)!=2 or {x['stream'] for x in packets}!={0,1}:raise ValueError('Expected paired packet PTS')
    times=[Fraction(x['pts'])*Fraction(x['time_base']) for x in packets]
    if times[0]!=times[1] or abs(times[0]-t)>Fraction(1,1000000):raise ValueError('Physical lens PTS mismatch')


def prepare(base_manifest,replacements,registration,output,run_name):
    base_manifest,replacements,registration=(Path(p).resolve(strict=True) for p in (base_manifest,replacements,registration));output=Path(output).resolve();base=json.loads(base_manifest.read_text());new=json.loads(replacements.read_text());fit=json.loads(registration.read_text())
    if output.exists():raise FileExistsError(output)
    if not run_name or Path(run_name).name!=run_name:raise ValueError('Invalid run name')
    for name,digest in fit['input_sha256'].items():
        if sha(name)!=digest:raise ValueError(f'Registration input hash mismatch: {name}')
    for name,digest in fit['source_feature_sha256'].items():
        if sha(name)!=digest:raise ValueError(f'Registration feature hash mismatch: {name}')
    if fit['input_sha256'].get(str(replacements))!=sha(replacements):raise ValueError('Registration used another replacement dataset')
    source=base_manifest.parent;seed=source/'seed.ply'
    if sha(Path(base['dataset'])/'manifest.json')!=base['source_manifest_sha256'] or sha(base['command'][0])!=base['binary_sha256']:raise ValueError('Baseline source or trainer differs')
    for name,digest in base['model_hashes'].items():
        if sha(Path(base['model'])/name)!=digest:raise ValueError('Baseline source model differs')
    for name in ('images.bin','points3D.bin','rigs.txt'):
        if fit['input_sha256'].get(str(Path(base['model'])/name))!=base['model_hashes'][name]:raise ValueError('Registration used another baseline model')
    if sha(seed)!=base['seed_sha256'] or fit['input_sha256'].get(str(seed))!=sha(seed):raise ValueError('Original seed mismatch')
    fitrows={r['source_frame']:r for r in fit['frames']};newrows={r['source_frame']:r for r in new['frames']}
    if len(fitrows)!=len(fit['frames']) or len(newrows)!=len(new['frames']) or set(fitrows)!=set(newrows):raise ValueError('Registration/replacement inventory mismatch')
    changed={r['anchor']:r for r in new['frames'] if r['anchor']!=r['source_frame']}
    if len(changed)!=12 or len(newrows)!=13 or 1350 not in newrows or newrows[1350]['anchor']!=1350:raise ValueError('Expected twelve replacements and unchanged 1350 control')
    if any(not fitrows[r['source_frame']]['accepted'] or fitrows[r['source_frame']]['anchor_source_frame']!=r['anchor'] or fitrows[r['source_frame']]['timestamp_microseconds']!=r['timestamp_microseconds'] for r in newrows.values()):raise ValueError('Unaccepted or mismatched registered pose')
    if len(fit['cam_from_rig'])!=2:raise ValueError('Expected two physical lenses')
    cameras=fit['cam_from_rig'];records=base['frames'];index={r['name']:r for r in records}
    if len(index)!=len(records) or len(records)!=824 or len(base['heldout_evaluation_order'])!=36:raise ValueError('Unexpected baseline inventory')
    points=(source/'sparse/0/points3D.txt').read_text().splitlines()
    if any(line.strip() and not line.lstrip().startswith('#') for line in points):raise ValueError('Training overlay cannot contain point tracks')
    config=json.loads((source.parent/'run/config.json').read_text())
    if config.get('refine_stop_iter')!=0 or config.get('refine_stop_num_iter')!=2000:raise ValueError('Baseline refinement configuration differs')
    lines=(source/'sparse/0/images.txt').read_text().splitlines();headers={}
    if len(lines)!=2*len(records):raise ValueError('Expected association-free training cameras')
    for line,blank in zip(lines[::2],lines[1::2]):
        values=line.split()
        if blank.strip() or len(values)!=10 or values[9] not in index or values[9] in headers:raise ValueError('Invalid association-free image rows')
        record=index[values[9]]
        if int(values[0])!=record['colmap_image_id'] or int(values[8])!=record['colmap_camera_id']:raise ValueError('Baseline camera row identity differs')
        headers[values[9]]=line
    if len(headers)!=len(index):raise ValueError('Incomplete baseline pose inventory')
    # Validate the registration rig against each actual original physical pair.
    for anchor in changed:
        a=headers[f'train_{anchor:06d}_cam0.png'].split();b=headers[f'train_{anchor:06d}_cam1.png'].split()
        def pose(v):return Rotation.from_quat([*map(float,v[2:5]),float(v[1])]).as_matrix(),np.array(list(map(float,v[5:8])))
        r0,t0=pose(a);r1,t1=pose(b);rel=r1@r0.T;trans=t1-rel@t0
        if not np.allclose(rel,cameras[1]['rotation'],atol=1e-5) or not np.allclose(trans,cameras[1]['translation'],atol=1e-5):raise ValueError('Registration rig differs from baseline')
    if not np.allclose(cameras[0]['rotation'],np.eye(3),atol=1e-9) or not np.allclose(cameras[0]['translation'],0,atol=1e-9):raise ValueError('Unexpected reference lens extrinsic')
    output.mkdir();(output/'INCOMPLETE').write_text('Overlay not verified\n');(output/'images').mkdir();(output/'masks').mkdir();(output/'sparse/0').mkdir(parents=True)
    for name in ('cameras.txt','points3D.txt'):os.link(source/'sparse/0'/name,output/'sparse/0'/name)
    os.link(seed,output/'seed.ply');updated=[];newlines=[]
    for item in records:
        r=copy.deepcopy(item);anchor=r['source_frame'];lens=r['lens'];original=r['name']
        if anchor in changed:
            if r['split']!='train':raise ValueError('Replacement would alter heldout image')
            candidate=changed[anchor];frame=candidate['source_frame'];check_pts(candidate);fitrow=fitrows[frame];rotation,translation=compose(cameras[int(lens[-1])],fitrow['rig_from_world']);quat=Rotation.from_matrix(rotation).as_quat();q=[quat[3],quat[0],quat[1],quat[2]];r.update(name=f'train_{frame:06d}_{lens}.png',source_name=f'{lens}/frame_{frame:06d}.png',source_frame=frame,timestamp_microseconds=candidate['timestamp_microseconds'],source_packet_pts=candidate['source_packet_pts']);values=headers[original].split();header=' '.join([values[0],*[format(x,'.17g') for x in q],*[format(x,'.17g') for x in translation],values[8],r['name']])
            for folder in ('images','masks'):
                entry=candidate['lenses'][lens][folder];src=Path(entry['path']).resolve(strict=True)
                if sha(src)!=entry['sha256']:raise ValueError('Replacement image/mask hash mismatch')
                os.link(src,output/folder/r['name'])
        else:
            header=headers[original]
            for folder in ('images','masks'):os.link(source/folder/original,output/folder/original)
        updated.append(r);newlines.append(header+'\n\n')
    if len({r['name'] for r in updated})!=824:raise ValueError('Duplicate output camera')
    (output/'sparse/0/images.txt').write_text(''.join(newlines));order=[r['name'] for r in sorted(updated,key=lambda x:x['name']) if r['split']=='eval']
    if order!=base['heldout_evaluation_order'] or sum(r['split']=='train' for r in updated)!=788:raise ValueError('Evaluation order or camera count changed')
    for name in order:
        for folder in ('images','masks'):
            if sha(source/folder/name)!=sha(output/folder/name):raise ValueError('Heldout pixels changed')
        if headers[name]+'\n\n' not in newlines:raise ValueError('Heldout pose changed')
    manifest=copy.deepcopy(base);manifest.update(status='prepared training-only image/pose overlay',frames=updated,heldout_evaluation_order=order,seed_sha256=sha(seed),overlay={'base_manifest_sha256':sha(base_manifest),'replacements_sha256':sha(replacements),'registration_sha256':sha(registration),'replacement_count':len(changed),'note':'Training-only cameras with no 2D tracks; existing SfM model and PLY seed are unchanged.'})
    flags=manifest['command'];flags[flags.index('--data')+1]=str(output);flags[flags.index('--output-dir-prefix')+1]=str(output.parent);flags[flags.index('--output-dir-name')+1]=run_name;flags[flags.index('--num-iterations')+1]='6000';flags[flags.index('--steps-per-save')+1]='6000';flags[flags.index('--save-full-checkpoint')+1]='0';flags+=['--refine-stop-iter','0','--refine-stop-num-iter','2000'];manifest['save_full_checkpoint']=False
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');(output/'INCOMPLETE').unlink();return manifest


def verify(base_manifest,replacements,registration,prepared):
    prepared=Path(prepared).resolve(strict=True);manifest=json.loads((prepared/'manifest.json').read_text())
    if (prepared/'INCOMPLETE').exists():raise ValueError('Overlay is incomplete')
    command=manifest['command'];run_name=command[command.index('--output-dir-name')+1]
    with tempfile.TemporaryDirectory(prefix='.verify-overlay-',dir=prepared.parent) as tmp:
        expected_dir=Path(tmp)/'prepared';expected=prepare(base_manifest,replacements,registration,expected_dir,run_name)
        ec=expected['command'];ec[ec.index('--data')+1]=str(prepared);ec[ec.index('--output-dir-prefix')+1]=str(prepared.parent)
        if expected!=manifest:raise ValueError('Overlay manifest differs from recomputed inputs')
        for folder in ('images','masks'):
            expected_names={x.name for x in (expected_dir/folder).iterdir()};actual_names={x.name for x in (prepared/folder).iterdir()}
            if expected_names!=actual_names:raise ValueError('Overlay file inventory differs')
            if any(not os.path.samefile(expected_dir/folder/n,prepared/folder/n) for n in expected_names):raise ValueError('Overlay file identity differs')
        for name in ('seed.ply','sparse/0/cameras.txt','sparse/0/points3D.txt'):
            if not os.path.samefile(expected_dir/name,prepared/name):raise ValueError('Overlay source file identity differs')
        if (expected_dir/'sparse/0/images.txt').read_bytes()!=(prepared/'sparse/0/images.txt').read_bytes():raise ValueError('Overlay poses differ from registered inputs')
    output=prepared.parent/run_name
    if output.exists() or output.is_symlink():raise FileExistsError(output)
    return command,output,788,36,6000


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('base_manifest','replacements','registration','output'):p.add_argument(name,type=Path)
    p.add_argument('--run-name',required=True);a=p.parse_args();m=prepare(a.base_manifest,a.replacements,a.registration,a.output,a.run_name);print(json.dumps({'cameras':len(m['frames']),'overlay':m['overlay']},indent=2))
if __name__=='__main__':main()
