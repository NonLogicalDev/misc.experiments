#!/usr/bin/env python3
"""Preserve selected native lens and existing panorama frames with exact PTS."""
import argparse, hashlib, json, re, subprocess
from fractions import Fraction
from pathlib import Path

def run(*args):
    return subprocess.check_output(args, text=True)

def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024*1024), b''): h.update(chunk)
    return h.hexdigest()

def probe(path, stream):
    data = json.loads(run('ffprobe','-v','error','-select_streams',f'v:{stream}','-show_streams','-show_packets','-show_entries','stream=index,width,height,time_base,codec_name:packet=pts','-of','json',str(path)))
    info = data['streams'][0]
    frames = sorted(data['packets'], key=lambda f: int(f['pts']))
    if len({f['pts'] for f in frames}) != len(frames): raise ValueError('duplicate packet PTS')
    for f in frames:
        if 'pts' not in f: raise ValueError(f'Frame has no PTS in {path} stream {stream}')
    return info, frames

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--panorama', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--panorama-frame', type=int, action='append', required=True, help='Zero-based decoded frame index; repeat for each sample')
    p.add_argument('--export-settings', type=Path, required=True, help='JSON evidence, with unknown settings explicitly noted')
    a = p.parse_args()
    if a.output.exists(): p.error('output must not exist')
    if len(set(a.panorama_frame)) != len(a.panorama_frame) or min(a.panorama_frame) < 0: p.error('frame indices must be distinct and nonnegative')
    settings = json.loads(a.export_settings.read_text())
    source = [probe(a.source, i) for i in range(2)]
    pano = probe(a.panorama, 0)
    samples = []
    for index in a.panorama_frame:
        if index >= len(pano[1]): p.error(f'panorama frame {index} out of range')
        pf = pano[1][index]; pt = Fraction(int(pf['pts'])) * Fraction(pano[0]['time_base'])
        matches = []
        for info, frames in source:
            tb = Fraction(info['time_base'])
            n = min(range(len(frames)), key=lambda j: abs(Fraction(int(frames[j]['pts']))*tb-pt))
            matches.append((n, frames[n], Fraction(int(frames[n]['pts']))*tb-pt))
        samples.append((index,pf,matches))
    a.output.mkdir(parents=True)
    manifest = {'schema':1,'source':{'path':str(a.source.resolve()),'sha256':sha(a.source),'streams':[s[0] for s in source]},'panorama':{'path':str(a.panorama.resolve()),'sha256':sha(a.panorama),'stream':pano[0]},'export_settings':settings,'ffmpeg_version':run('ffmpeg','-version').splitlines()[0], 'matching':'nearest packet presentation time, checked against decoded frame PTS; does not prove capture synchronization or exporter correspondence','samples':[]}
    for index,pf,matches in samples:
        entry={'panorama_frame':index,'panorama_pts':pf['pts'],'panorama_time_base':pano[0]['time_base'],'images':[]}
        for label,path,stream,n,frame,delta in [('panorama',a.panorama,0,index,pf,Fraction(0))]+[(f'lens{i}',a.source,i,n,f,d) for i,(n,f,d) in enumerate(matches)]:
            name=f'frame-{index:06d}-{label}.png'; dest=a.output/name
            result = subprocess.run(['ffmpeg','-v','info','-copyts','-i',str(path),'-map',f'0:v:{stream}','-vf',f'select=eq(n\\,{n}),showinfo','-fps_mode','vfr','-frames:v','1',str(dest)],check=True, capture_output=True, text=True)
            found = re.search(r'\bn:\s*0\s+pts:\s*(-?\d+)', result.stderr)
            if not found or int(found.group(1)) != int(frame['pts']): raise ValueError(f'decoded PTS mismatch for {label} frame {n}; packet indexing is not valid')
            entry['images'].append({'role':label,'stream':stream,'decoded_frame':n,'pts':frame['pts'],'time_base':(pano[0] if label=='panorama' else source[stream][0])['time_base'],'delta_from_panorama_seconds':str(delta),'path':name,'sha256':sha(dest)})
        manifest['samples'].append(entry)
    (a.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')

if __name__ == '__main__': main()
