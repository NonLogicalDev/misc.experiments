#!/usr/bin/env python3
"""Create a BT.709 compatibility preview from canonical observation PNGs."""
import argparse, hashlib, json, subprocess
from pathlib import Path
import numpy as np
from PIL import Image

def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
 if a.output.exists() or a.output.with_suffix('.json').exists():p.error('output already exists')
 m=json.loads((a.input/'manifest.json').read_text())
 if 'frames' in m: frames=m['frames']
 else:
  frames=[{'frame':m['first_frame']+i,'images':{role:m['outputs'][role][i] for role in ('color','validity')}} for i in range(m['frame_count'])]
 first=frames[0]['frame'];n=len(frames)
 for f in frames:
  for role in ('color','validity'):
   item=f['images'][role]
   if sha(a.input/item['path'])!=item['sha256']:raise ValueError('source hash mismatch')
 cmd=['ffmpeg','-v','error','-framerate','30000/1001','-start_number',str(first),'-i',str(a.input/'color/frame_%08d.png'),'-vf','scale=in_range=full:out_range=tv:out_color_matrix=bt709,format=yuv420p','-c:v','libx264','-crf','15','-color_range','tv','-colorspace','bt709','-color_primaries','bt709','-color_trc','bt709','-x264-params','colorprim=bt709:transfer=bt709:colormatrix=bt709',str(a.output)]
 subprocess.run(cmd,check=True)
 probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=width,height,nb_frames,pix_fmt,color_range,color_space,color_transfer,color_primaries','-of','json',str(a.output)],text=True))['streams'][0]
 if any(probe.get(k)!=v for k,v in {'pix_fmt':'yuv420p','color_range':'tv','color_space':'bt709','color_transfer':'bt709','color_primaries':'bt709'}.items()) or int(probe['nb_frames'])!=n:raise ValueError('unexpected preview format')
 w,h=probe['width'],probe['height'];proc=subprocess.Popen(['ffmpeg','-v','error','-i',str(a.output),'-f','rawvideo','-pix_fmt','rgb24','-'],stdout=subprocess.PIPE); hist=np.zeros((3,256),np.int64);signed=np.zeros(3,np.int64);count=0;invalid_nonblack=0;invalid_count=0
 for f in frames:
  data=proc.stdout.read(w*h*3)
  if len(data)!=w*h*3:raise ValueError('truncated decode')
  out=np.frombuffer(data,np.uint8).reshape(h,w,3); src=np.asarray(Image.open(a.input/f['images']['color']['path']).convert('RGB'));valid=np.asarray(Image.open(a.input/f['images']['validity']['path']).convert('L'))>0
  delta=out[valid].astype(np.int16)-src[valid].astype(np.int16); count+=len(delta); signed+=delta.sum(axis=0); invalid_count+=np.count_nonzero(~valid); invalid_nonblack+=np.count_nonzero(np.any(out[~valid]!=0,axis=1))
  for c in range(3):hist[c]+=np.bincount(np.abs(delta[:,c]),minlength=256)
 if proc.wait()!=0:raise ValueError('preview decode failed')
 result={'source_manifest_sha256':sha(a.input/'manifest.json'),'video_sha256':sha(a.output),'stream':probe,'frames_compared':n,'valid_pixels_compared':count,'mean_absolute_rgb_error':[float((hist[c]*np.arange(256)).sum()/count) for c in range(3)],'p95_absolute_rgb_error':[int(np.searchsorted(np.cumsum(hist[c]),.95*count)) for c in range(3)],'mean_signed_rgb_error':(signed/count).tolist(),'invalid_pixels':int(invalid_count),'invalid_nonblack_after_decode':int(invalid_nonblack),'note':'Preview uses chroma subsampling and lossy compression; PNG observations and validity masks are canonical. Nonblack invalid pixels include codec and chroma boundary effects.'}
 a.output.with_suffix('.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
if __name__=='__main__':main()
