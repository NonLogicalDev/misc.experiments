#!/usr/bin/env python3
"""Stage actual capture rows for a local fit diagnostic; preserve source poses."""
import argparse,hashlib,json,os
from pathlib import Path

def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()

def prepare(manifest,output,train_names,eval_names):
 manifest=Path(manifest).resolve(strict=True);source=manifest.parent;output=Path(output).resolve();base=json.loads(manifest.read_text());train_names=list(train_names);eval_names=list(eval_names)
 if not train_names or not eval_names or len(set(train_names+eval_names))!=len(train_names+eval_names):raise ValueError('Require unique, disjoint training and evaluation captures')
 if output.exists():raise FileExistsError(output)
 records={}
 for name in train_names+eval_names:
  rows=[r for r in base['frames'] if r['name']==name]
  if len(rows)!=1 or (name in train_names and rows[0]['split']!='train'):raise ValueError('Missing, duplicate, or non-training selected capture: '+name)
  records[name]=rows[0]
 lines=(source/'sparse/0/images.txt').read_text().splitlines();poses={}
 for line in lines:
  tokens=line.split()
  if len(tokens)==10 and tokens[-1] in records:
   if tokens[-1] in poses:raise ValueError('Duplicate pose')
   poses[tokens[-1]]=tokens
 if set(poses)!=set(records):raise ValueError('Missing camera pose')
 for n,row in poses.items():
  if 'colmap_image_id' in records[n] and (int(row[0])!=records[n]['colmap_image_id'] or int(row[-2])!=records[n]['colmap_camera_id']):raise ValueError('Manifest and pose IDs differ')
 if sha(source/'seed.ply')!=base['seed_sha256']:raise ValueError('Seed hash mismatch')
 names={n:('eval_'+n[6:] if n in eval_names and n.startswith('train_') else n) for n in records}
 if len(set(names.values()))!=len(names) or any(not names[n].startswith('eval_') for n in eval_names):raise ValueError('Invalid evaluation names')
 evidence=[]
 for n in records:
  image=source/'images'/n;mask=source/'masks'/n
  evidence.append({'original_name':n,'staged_name':names[n],'original_split':records[n]['split'],'diagnostic_split':'train' if n in train_names else 'eval','image_sha256':sha(image),'mask_sha256':sha(mask),'pose':poses[n][:-1]})
 output.mkdir();(output/'INCOMPLETE').write_text('Incomplete\n');data=output/'data';(data/'images').mkdir(parents=True);(data/'masks').mkdir();(data/'sparse/0').mkdir(parents=True)
 for n in records:
  for d in ('images','masks'):os.link(source/d/n,data/d/names[n])
 for n in ('seed.ply','sparse/0/cameras.txt'):os.link(source/n,data/n)
 (data/'sparse/0/points3D.txt').write_text('# Diagnostic seed supplied as PLY; no tracks\n'); rows=[]
 for n in records:
  row=poses[n].copy();row[-1]=names[n];rows.extend([' '.join(row),''])
 (data/'sparse/0/images.txt').write_text('\n'.join(rows)+'\n');result={'source_manifest':str(manifest),'source_manifest_sha256':sha(manifest),'seed_sha256':base['seed_sha256'],'camera_sha256':sha(source/'sparse/0/cameras.txt'),'frames':evidence};(output/'staging.json').write_text(json.dumps(result,indent=2)+'\n');(output/'INCOMPLETE').unlink();return result

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('manifest');p.add_argument('output');p.add_argument('--train',nargs='+',required=True);p.add_argument('--eval',nargs='+',required=True);a=p.parse_args();prepare(a.manifest,a.output,a.train,a.eval)
if __name__=='__main__':main()
