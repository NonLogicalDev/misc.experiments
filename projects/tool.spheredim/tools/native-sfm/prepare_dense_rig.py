#!/usr/bin/env python3
"""Plan or prepare a bounded denser physical-lens rig dataset from reviewed candidates."""
import argparse
import csv
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

import prepare_rig as rig

RESERVE = 35 * 1024**3
BUDGET = 400 * 1024**2
DIRS = ('images','masks','feature-masks','guarded-masks','eval-masks','operator-keep','lens-support')


def sha(path): return rig.sha(path)


def plan(base, candidates, source, fit, native, runner, batch_size):
    base, candidates, source, fit, native, runner = (Path(x).resolve(strict=True) for x in (base,candidates,source,fit,native,runner))
    baseline=json.loads((base/'manifest.json').read_text());candidate=json.loads((candidates/'manifest.json').read_text());review=json.loads((candidates/'visual-review.json').read_text())
    if sha(candidates/'manifest.json')!=review['generation_manifest_sha256'] or review['frames_inspected']!=len(candidate['frames']):raise ValueError('Candidate review provenance mismatch')
    if review['reviewed_sheet_hashes']!=candidate['sheets'] or any(sha(candidates/'review'/s['name'])!=s['sha256'] for s in review['reviewed_sheet_hashes']):raise ValueError('Review sheet hash mismatch')
    frames=candidate['frames'];indices=[r['source_frame'] for r in frames]
    if indices!=sorted(set(indices)) or len(indices)<2:raise ValueError('Candidate frames must be unique and sorted')
    old={r['source_frame']:r for r in baseline['frames']}
    if not set(old).issubset(indices):raise ValueError('Candidate set does not include all baseline timestamps')
    if baseline['spatial_split']!='No held-out features; every guarded location is available for training and evaluation masks are empty.':raise ValueError('Baseline must use no spatial split')
    if sha(fit)!=baseline['fit_rig_sha256']:raise ValueError('Rig fit differs from baseline')
    probe=json.loads(Path(baseline['source_manifest']).read_text()); provenance=probe['provenance']
    if sha(Path(baseline['source_manifest']))!=baseline['source_manifest_sha256'] or sha(source)!=probe['source_sha256'] or sha(native)!=provenance['native_extension_sha256'] or sha(runner)!=provenance['runner_sha256']:
        raise ValueError('Baseline source, native exporter or runner identity differs')
    for r in frames:
        n=r['source_frame'];mask=candidates/'stabilized'/r['mask']
        if sha(mask)!=r['stabilized_sha256']:raise ValueError(f'Candidate mask changed: {n}')
        if n in old and old[n]['review_mask_sha256']!=r['stabilized_sha256']:raise ValueError(f'Baseline key differs: {n}')
    if batch_size<2 or batch_size>32:raise ValueError('Batch size must be 2..32')
    additions=[n for n in indices if n not in old]
    return {'baseline':baseline,'candidate':candidate,'probe':probe,'old':old,'indices':indices,'additions':additions,'batches':[additions[i:i+batch_size] for i in range(0,len(additions),batch_size)],'paths':{'base':base,'candidates':candidates,'source':source,'fit':fit,'native':native,'runner':runner}}


def disk_usage(root, excluded):
    seen=set();total=0
    for p in root.rglob('*'):
        if not p.is_file():continue
        st=p.stat();identity=(st.st_dev,st.st_ino)
        if identity not in seen and identity not in excluded:total+=st.st_size;seen.add(identity)
    return total


def check(root, excluded):
    if disk_usage(root,excluded)>BUDGET or shutil.disk_usage(root).free<RESERVE:raise RuntimeError('400 MiB output cap or 35 GiB reserve exceeded')


def monitor(cmd,env,root,excluded,log,timeout,on_progress=None):
    started=time.monotonic()
    with log.open('w') as f:
        proc=subprocess.Popen(cmd,stdout=f,stderr=subprocess.STDOUT,env=env,start_new_session=True);deadline=time.monotonic()+timeout
        try:
            while proc.poll() is None:
                check(root,excluded)
                if on_progress:on_progress()
                if time.monotonic()>deadline:raise TimeoutError('Exporter timed out')
                time.sleep(1)
        except BaseException:
            os.killpg(proc.pid,signal.SIGTERM)
            try:proc.wait(timeout=10)
            except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait(timeout=10)
            raise
        if proc.returncode:raise RuntimeError(f'Exporter failed ({proc.returncode}); see {log}')
        check(root,excluded)
    return time.monotonic()-started


def packet_map(source):
    data=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v','-show_streams','-show_packets','-show_entries','stream=index,time_base:packet=stream_index,pts','-of','json',str(source)],timeout=300))
    streams={x['index']:Fraction(x['time_base']) for x in data['streams']}
    if len(streams)!=2:raise ValueError('Expected exactly two physical lens video streams')
    packets={n:[] for n in streams}
    for p in data['packets']:
        if p['stream_index'] in packets and 'pts' in p:packets[p['stream_index']].append(int(p['pts']))
    return streams,packets


def matched_pts(timestamp,streams,packets):
    t=Fraction(timestamp,1000000);result=[]
    for stream,tb in sorted(streams.items()):
        matches=[v for v in packets[stream] if abs(v*tb-t)<=Fraction(1,1000000)]
        if len(matches)!=1:raise ValueError('Physical lens packet PTS not uniquely matched')
        result.append({'stream':stream,'pts':matches[0],'time_base':str(tb),'delta_from_exporter_pair_seconds':str(matches[0]*tb-t)})
    return result


def prepare(p,output,fused,batch_timeout,pilot=False,seek=False):
    output=Path(output).resolve();fused=Path(fused).resolve(strict=True)
    if output.exists():raise FileExistsError(output)
    if sha(fused)!=p['baseline']['fused_csv_sha256']:raise ValueError('Orientation CSV differs from baseline')
    if shutil.disk_usage(output.parent).free<RESERVE+BUDGET:raise RuntimeError('Need 35 GiB free reserve plus 400 MiB budget')
    base=p['paths']['base'];candidate=p['paths']['candidates'];source=p['paths']['source'];fit=p['paths']['fit'];native=p['paths']['native'];runner=p['paths']['runner']
    excluded={(f.stat().st_dev,f.stat().st_ino) for d in DIRS for f in (base/d).rglob('*.png')}
    output.mkdir();(output/'INCOMPLETE').write_text('Preparation incomplete; not ready for reconstruction\n')
    started=time.monotonic()
    def status(stage,completed,total,batch=None,done=False):
        payload={'status':'complete' if done else 'running','stage':stage,'completed_timestamps':completed,'total_timestamps':total,'elapsed_seconds':time.monotonic()-started,'incremental_output_bytes':disk_usage(output,excluded),'free_bytes':shutil.disk_usage(output).free,'output_budget_bytes':BUDGET,'minimum_free_bytes':RESERVE}
        if batch is not None:payload['batch']=batch
        tmp=output/'status.json.tmp';tmp.write_text(json.dumps(payload,indent=2)+'\n');tmp.replace(output/'status.json')
    status('Reusing verified baseline frames',0,len(p['indices']))
    for d in DIRS:
        for lens in ('cam0','cam1'):(output/d/lens).mkdir(parents=True)
    records=[]
    for n,frame in sorted(p['old'].items()):
        for lens in ('cam0','cam1'):
            name=f'frame_{n:06d}.png';info=frame['lenses'][lens]
            for directory in DIRS:
                src=base/directory/lens/name
                key={'images':'image_sha256','masks':'mask_sha256','feature-masks':'feature_mask_sha256','eval-masks':'evaluation_mask_sha256'}.get(directory)
                if key and sha(src)!=info[key]:raise ValueError(f'Baseline hash mismatch: {src}')
                os.link(src,output/directory/lens/name)
        records.append(frame)
    for name in ('rig-zero.json','rig-separated.json','rig-metadata.json','rig-fitted-metric.json','rig-baseline-provenance.json'):
        os.link(base/name,output/name)
    (output/'candidate-review').mkdir();(output/'review-new').mkdir();(output/'provenance').mkdir();os.symlink(candidate/'stabilized',output/'candidate-review/masks',target_is_directory=True)
    cm={'status':'controlled experiment: visually inspected propagated candidates, not segmentation ground truth','frame_dimensions':[1024,512],'frames':[{'source_frame':r['source_frame'],'video_pts_s':r['video_pts_s'],'mask':r['mask']} for r in p['candidate']['frames']]}
    review_path=output/'candidate-review/manifest.json';review_path.write_text(json.dumps(cm,indent=2)+'\n')
    status('Checking physical-lens packet timestamps',len(records),len(p['indices']))
    streams,packets=packet_map(source);history=[]
    env=os.environ.copy();env.pop('SPHEREDIM_LENS1_INVERSE_QUAT_WXYZ',None);env.pop('SPHEREDIM_OBSERVATION_MODE',None);env['PYTHONPATH']=str(native.parent.parent);env['UV_CACHE_DIR']='/private/tmp/insv-uv-cache'
    chosen_batches=p['batches'][:1] if pilot else p['batches']
    for batch_number,indices in enumerate(chosen_batches):
        check(output,excluded);stage=output/f'.batch-{batch_number:03d}';stage.mkdir();export=stage/'export';log=output/f'export-{batch_number:03d}.log'
        prefix=['uv','run','--offline','--isolated','--no-project','--python','3.12','--with','numpy','--with','pillow','python']
        if seek:
            by_frame={r['source_frame']:r for r in p['candidate']['frames']}
            exporter=Path(__file__).with_name('export_timestamp_probes.py')
            cmd=prefix+[str(exporter),'--source',str(source),'--output',str(export),'--indices',*map(str,indices),'--timestamps',*[str(by_frame[n]['video_pts_s']) for n in indices]]
        else:
            cmd=prefix+[str(runner),'--source',str(source),'--output',str(export),'--indices',*map(str,indices),'--validation',str(indices[0]),'--width','2048']
        update=lambda:status('Exporting physical-lens observations',len(records),len(p['indices']),batch_number+1)
        status('Exporting physical-lens observations',len(records),len(p['indices']),batch_number+1)
        export_seconds=monitor(cmd,env,output,excluded,log,batch_timeout,update)
        probe_path=export/'manifest.json';probe=json.loads(probe_path.read_text())
        if probe['source_sha256']!=p['probe']['source_sha256'] or [f['frame'] for f in probe['frames']]!=indices:raise ValueError('Exporter output source or frame mismatch')
        by_frame={r['source_frame']:r for r in p['candidate']['frames']}
        for frame in probe['frames']:
            n=frame['frame'];c=by_frame[n]
            if abs(frame['timestamp_microseconds']/1e6-c['video_pts_s'])>1e-5:raise ValueError(f'Candidate PTS mismatch: {n}')
            frame['source_packet_pts']=matched_pts(frame['timestamp_microseconds'],streams,packets)
            mask=candidate/'stabilized'/c['mask'];frame['reviewed_operator_mask']={'path':str(mask),'sha256':sha(mask),'video_pts_s':c['video_pts_s'],'coordinates':'FlowState ERP; inspected propagated candidate'}
        probe_path.write_text(json.dumps(probe,indent=2)+'\n')
        prepared=stage/'prepared'
        prepare_cmd=[sys.executable,str(Path(__file__).with_name('prepare_rig.py')),str(probe_path),str(review_path),str(fused),str(fit),str(prepared),'--guard','16','--split','none','--max-output-mib','96']
        update=lambda:status('Preparing spherical images and masks',len(records),len(p['indices']),batch_number+1)
        status('Preparing spherical images and masks',len(records),len(p['indices']),batch_number+1)
        prepare_seconds=monitor(prepare_cmd,env,output,excluded,output/f'prepare-{batch_number:03d}.log',batch_timeout,update)
        data=json.loads((prepared/'manifest.json').read_text())
        for frame in data['frames']:
            n=frame['source_frame'];name=f'frame_{n:06d}.png'
            for lens in ('cam0','cam1'):
                info=frame['lenses'][lens]
                for directory in DIRS:
                    src=prepared/directory/lens/name
                    key={'images':'image_sha256','masks':'mask_sha256','feature-masks':'feature_mask_sha256','eval-masks':'evaluation_mask_sha256'}.get(directory)
                    if key and sha(src)!=info[key]:raise ValueError(f'Prepared image hash mismatch: {src}')
                    os.link(src,output/directory/lens/name)
            records.append(frame)
        for lens in ('cam0','cam1'):
            sheet=prepared/f'{lens}-review-001.png'
            os.link(sheet,output/'review-new'/f'{lens}-{batch_number:03d}.png')
        os.link(probe_path,output/'provenance'/f'probe-{batch_number:03d}.json')
        os.link(prepared/'manifest.json',output/'provenance'/f'prepared-{batch_number:03d}.json')
        history.append({'indices':indices,'selection':'timestamp-seek' if seek else 'index','export_seconds':export_seconds,'prepare_seconds':prepare_seconds,'source_manifest_sha256':sha(probe_path),'prepared_manifest_sha256':sha(prepared/'manifest.json'),'review_sheets':{lens:sha(output/'review-new'/f'{lens}-{batch_number:03d}.png') for lens in ('cam0','cam1')},'source_observation_hashes':[{'frame':f['frame'],**{k:f[k] for k in ('lens0_sha256','lens1_sha256','mask0_sha256','mask1_sha256')}} for f in probe['frames']]})
        # Only this invocation's temporary batch is removed after its data and hashes are recorded.
        shutil.rmtree(stage);check(output,excluded)
    records.sort(key=lambda x:x['source_frame'])
    expected=sorted(set(p['old']) | {n for batch in chosen_batches for n in batch})
    if [r['source_frame'] for r in records]!=expected:raise ValueError('Final dataset coverage mismatch')
    meta={**p['baseline'],'status':('pilot subset only; not the complete dense dataset' if pilot else 'controlled experiment; propagated operator candidates require per-lens overlay review'),'source_manifest':p['baseline']['source_manifest'],'source_manifest_note':'Baseline timestamps only; new per-batch source observations verified then discarded after preparation, with hashes and manifest copies in batch_history and provenance/','review_manifest_sha256':sha(review_path),'candidate_manifest_sha256':sha(candidate/'manifest.json'),'candidate_review_sha256':sha(candidate/'visual-review.json'),'baseline_manifest_sha256':sha(base/'manifest.json'),'batch_history':history,'frames':records}
    (output/'manifest.json').write_text(json.dumps(meta,indent=2)+'\n')
    status('Generating matching rotation priors',len(records),len(expected))
    prior_cmd=[sys.executable,str(Path(__file__).with_name('export_rotation_priors.py')),str(output/'manifest.json'),str(output/'rig-metadata.json'),str(fused),str(output/'rotation-priors.csv'),str(output/'rotation-priors.provenance.json'),'--sigma-degrees','1']
    monitor(prior_cmd,env,output,excluded,output/'rotation-priors.log',batch_timeout)
    def read_priors(path):
        with path.open(newline='') as f: rows=list(csv.DictReader(f))
        result={row['image']:row for row in rows}
        if len(result)!=len(rows):raise ValueError(f'Duplicate rotation prior in {path}')
        return result
    baseline_priors=read_priors(base/'rotation-priors.csv');dense_priors=read_priors(output/'rotation-priors.csv')
    expected_images={f'{lens}/frame_{n:06d}.png' for n in expected for lens in ('cam0','cam1')}
    if set(dense_priors)!=expected_images or any(dense_priors.get(k)!=v for k,v in baseline_priors.items()):raise ValueError('Rotation priors differ from baseline or dataset coverage')
    check(output,excluded);(output/'INCOMPLETE').unlink()
    status('Pilot prepared; lens overlays require review' if pilot else 'Prepared; lens overlays require review',len(records),len(expected),done=True)


def main():
    a=argparse.ArgumentParser(description=__doc__)
    for name in ('baseline','candidates','source','fit','native','runner','fused','output'):a.add_argument(name,type=Path)
    a.add_argument('--batch-size',type=int,default=16);a.add_argument('--batch-timeout',type=int,default=600);a.add_argument('--execute',action='store_true',help='Perform GPU lens exports; otherwise validate inputs and print plan');a.add_argument('--pilot',action='store_true',help='Prepare only the first batch of new timestamps');a.add_argument('--seek',action='store_true',help='Use timestamp selection with per-frame PTS checks')
    args=a.parse_args();p=plan(args.baseline,args.candidates,args.source,args.fit,args.native,args.runner,args.batch_size)
    if not args.execute:
        print(json.dumps({'mode':'plan only; no export','total':len(p['indices']),'baseline_reuse':len(p['old']),'new':len(p['additions']),'batch_size':args.batch_size,'batches':len(p['batches']),'output_budget_bytes':BUDGET,'minimum_free_bytes':RESERVE,'gpu':'4 physical-lens export passes per batch; do not launch without GPU coordination'},indent=2));return
    try:
        prepare(p,args.output,args.fused,args.batch_timeout,args.pilot,args.seek)
    except BaseException as error:
        path=args.output/'status.json'
        if path.exists():
            data=json.loads(path.read_text());data.update(status='failed',error=str(error))
            tmp=path.with_suffix('.json.tmp');tmp.write_text(json.dumps(data,indent=2)+'\n');tmp.replace(path)
        raise


if __name__=='__main__':main()
