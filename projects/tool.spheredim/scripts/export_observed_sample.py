#!/usr/bin/env python3
"""Export a bounded experimental single-lens sample with aligned PNG sidecars.

Requires the separately composed observation patch; never use an ordinary wheel.
"""
import argparse, hashlib, json, os, re, subprocess, sys
from fractions import Fraction
from pathlib import Path


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''): h.update(block)
    return h.hexdigest()


def worker(a):
    import insta360_rs as ins
    config = ins.StitchConfig(backend=ins.ProcessingBackend.GPU, stabilization=ins.Stabilization.FLOW_STATE,
        rolling_shutter=ins.RollingShutterCorrection.OFF, seam_mode=ins.SeamMode.FIXED, width=a.width, height=a.width//2)
    job=ins.start_export_frames(str(a.source),str(a.output),indices=list(range(a.first,a.first+a.count)),config=config,format=ins.ImageFormat.PNG)
    result=job.wait()
    if result.frames_written != a.count: raise RuntimeError(f'expected {a.count} frames, got {result.frames_written}')
    print(json.dumps({'outputs':[str(p) for p in result.outputs], 'backend':str(result.backend.selected)}))


def validate_frame(rgb, mask, own):
    import numpy as np
    if rgb.shape != mask.shape or rgb.shape != own.shape or rgb.ndim != 3 or rgb.shape[2] != 3: raise ValueError('frame dimensions differ')
    if not np.all((mask==0)|(mask==255)) or not np.all(mask[:,:,0]==mask[:,:,1]) or not np.all(mask[:,:,1]==mask[:,:,2]): raise ValueError('non-binary validity')
    valid=mask[:,:,0]==255
    if np.any(rgb[~valid]!=0) or np.any(own[~valid]!=0): raise ValueError('invalid pixel not black')
    if np.any((own[valid]!=[255,0,0]).any(axis=1) & (own[valid]!=[0,255,0]).any(axis=1)): raise ValueError('invalid ownership')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True); p.add_argument('--output',type=Path,required=True)
    p.add_argument('--first',type=int,default=900); p.add_argument('--count',type=int,default=90)
    p.add_argument('--width',type=int,default=2048); p.add_argument('--margin-degrees',type=float,default=0,help='Spherical margin around invalid pixels'); p.add_argument('--alignment-report',type=Path, help='Fixed lens1-to-lens0 fit; inverse quaternion is used for sampling'); p.add_argument('--worker',action='store_true',help=argparse.SUPPRESS)
    a=p.parse_args()
    if a.worker: return worker(a)
    if a.output.exists(): p.error('output already exists')
    if a.first<0 or not 1<=a.count<=150 or a.width<128 or a.width%2 or not 0<=a.margin_degrees<90: p.error('invalid bounded selection or margin')
    # The patched module must export this sentinel; refuse an ordinary wheel.
    import insta360_rs._native as native
    binary=Path(native.__file__)
    if b'SPHEREDIM_OBSERVATION_MODE' not in binary.read_bytes(): p.error('installed extension does not contain the observation patch')
    alignment=None
    if a.alignment_report:
        if b'SPHEREDIM_LENS1_INVERSE_QUAT_WXYZ' not in binary.read_bytes(): p.error('extension cannot apply fixed lens alignment')
        report=json.loads(a.alignment_report.read_text()); q=report['quaternion_xyzw']
        if len(q)!=4 or not all(isinstance(x,(int,float)) and abs(x)<2 for x in q) or abs(sum(x*x for x in q)-1)>1e-5: raise ValueError('invalid fit quaternion')
        alignment={'report':str(a.alignment_report.resolve()),'report_sha256':digest(a.alignment_report),'fit_quaternion_xyzw':q,'sampling_inverse_quaternion_wxyz':[q[3],-q[0],-q[1],-q[2]]}
    a.output.mkdir(parents=True)
    records={}
    for mode in ('color','validity','ownership'):
        env=os.environ.copy(); env['SPHEREDIM_OBSERVATION_MODE']=mode
        env.pop('SPHEREDIM_LENS1_INVERSE_QUAT_WXYZ',None)
        if alignment: env['SPHEREDIM_LENS1_INVERSE_QUAT_WXYZ']=','.join(str(x) for x in alignment['sampling_inverse_quaternion_wxyz'])
        cmd=[sys.executable,__file__,'--worker','--source',str(a.source),'--output',str(a.output/mode),'--first',str(a.first),'--count',str(a.count),'--width',str(a.width)]
        r=subprocess.run(cmd,env=env,text=True,capture_output=True,check=True)
        records[mode]=json.loads(r.stdout.strip().splitlines()[-1])
        records[mode]['timestamps']=[(int(i),int(t)) for i,t in re.findall(r'SPHEREDIM_FRAME (\d+) (-?\d+)',r.stderr)]
        if len(records[mode]['timestamps']) != a.count: raise ValueError('missing exporter timestamps')
    if records['color']['timestamps'] != records['validity']['timestamps'] or records['color']['timestamps'] != records['ownership']['timestamps']: raise ValueError('exporter timestamps differ between passes')
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v','-show_streams','-show_packets','-show_entries','stream=index,time_base:packet=stream_index,pts','-of','json',str(a.source)],text=True))
    streams={s['index']:s['time_base'] for s in probe['streams']}
    pts={i:sorted((int(p['pts']) for p in probe['packets'] if p['stream_index']==i)) for i in streams}
    source_pts=[]
    for frame,micros in records['color']['timestamps']:
        matched=[]
        for i,tb in streams.items():
            value=pts[i][frame]; delta=Fraction(value)*Fraction(tb)-Fraction(micros,1000000)
            if abs(delta)>Fraction(1,1000000): raise ValueError('paired timeline differs from source packet timeline')
            matched.append({'stream':i,'pts':value,'time_base':tb})
        source_pts.append({'frame':frame,'exporter_pair_timestamp_microseconds':micros,'source_packet_pts':matched})
    # Never mark masks valid without checking binary pixels, count and correspondence.
    from PIL import Image
    import numpy as np
    paths={k:[Path(x) for x in v['outputs']] for k,v in records.items()}
    if any(len(v)!=a.count for v in paths.values()): raise ValueError('export frame counts differ')
    for c,v,o in zip(paths['color'],paths['validity'],paths['ownership']):
        rgb=np.asarray(Image.open(c).convert('RGB')); mask=np.asarray(Image.open(v).convert('RGB')); own=np.asarray(Image.open(o).convert('RGB'))
        validate_frame(rgb, mask, own)
        if a.margin_degrees:
            from expand_observation_margin import angular_dilate
            invalid=angular_dilate(mask[:,:,0]==0,a.margin_degrees)
            rgb=rgb.copy(); mask=mask.copy(); own=own.copy()
            rgb[invalid]=0; mask[invalid]=0; own[invalid]=0
            validate_frame(rgb, mask, own)
            Image.fromarray(rgb).save(c); Image.fromarray(mask).save(v); Image.fromarray(own).save(o)
    if any(Fraction(source_pts[i+1]['source_packet_pts'][0]['pts']-source_pts[i]['source_packet_pts'][0]['pts'])*Fraction(source_pts[i]['source_packet_pts'][0]['time_base']) != Fraction(1001,30000) for i in range(len(source_pts)-1)):
        raise ValueError('source timeline is not the assumed 30000/1001 frame rate')
    # Lossless RGB encoding avoids chroma subsampling across validity boundaries.
    video=a.output/'observation.mp4'
    subprocess.run(['ffmpeg','-v','error','-framerate','30000/1001','-start_number',str(a.first),'-i',str(a.output/'color/frame_%08d.png'),'-c:v','libx264rgb','-crf','0','-pix_fmt','rgb24','-y',str(video)],check=True)
    def checksums(args):
        output=subprocess.check_output(['ffmpeg','-v','error',*args,'-pix_fmt','rgb24','-f','framemd5','-'],text=True)
        return [line.split(',')[-1].strip() for line in output.splitlines() if line and not line.startswith('#')]
    original=checksums(['-framerate','30000/1001','-start_number',str(a.first),'-i',str(a.output/'color/frame_%08d.png')])
    decoded=checksums(['-i',str(video)])
    if len(original)!=a.count or original!=decoded: raise ValueError('preview video decoded pixels differ from canonical frames')
    manifest={'experimental':True,'source_commit':'b4f3845feb105b70c1928ed4316fe1d8a963bc36','alignment':alignment,'input':str(a.source.resolve()),'input_sha256':digest(a.source),'patched_binary_sha256':digest(binary),'first_frame':a.first,'frame_count':a.count,'timestamps':source_pts,'preview_rate':'30000/1001','preview_rgb_verified_against_png':True,'backend_results':{k:v['backend'] for k,v in records.items()},'settings':{'width':a.width,'height':a.width//2,'backend':'GPU','stabilization':'FLOW_STATE','rolling_shutter':'OFF','seam':'FIXED','mode':'single source; uncertain crossover cut 0.45..0.55','angular_margin_degrees':a.margin_degrees},'ffmpeg_version':subprocess.check_output(['ffmpeg','-version'],text=True).splitlines()[0],'video_sha256':digest(video),'outputs':{k:[{'path':str(x.relative_to(a.output)),'sha256':digest(x)} for x in v] for k,v in paths.items()},'limits':'PNG frames are canonical; MP4 is a preview. Source packet indices match exporter paired timestamps within one microsecond; this does not prove physical synchronization, individual decoded source identity, calibration accuracy or geometric correctness.'}
    (a.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')

if __name__=='__main__': main()
