#!/usr/bin/env python3
"""Stage an observed one-view fitting diagnostic with a frozen-geometry plan."""
import argparse,copy,hashlib,json,os
from pathlib import Path


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()


def prepare(source_manifest,audit_manifest,ply,output,target):
    source_manifest,audit_manifest,ply=(Path(x).resolve(strict=True) for x in (source_manifest,audit_manifest,ply));output=Path(output).resolve();source=source_manifest.parent;base=json.loads(source_manifest.read_text());audit=json.loads(audit_manifest.read_text())
    if output.exists():raise FileExistsError(output)
    rows=[x for x in base['frames'] if x['name']==target and x['split']=='train'];reviews=[x for x in audit['frames'] if x['name']==target]
    if len(rows)!=1 or len(reviews)!=1:raise ValueError('Target must be one original training view in the verified 7k audit')
    row=rows[0];review=reviews[0];image=source/'images'/target;mask=source/'masks'/target;ref=audit_manifest.parent/'render'/f"eval-render-{review['index']:05d}.png"
    if sha(image)!=review['source_sha256'] or sha(mask)!=review['mask_sha256'] or sha(ref)!=review['render_sha256'] or sha(ply)!=audit['checkpoint_ply_sha256']:raise ValueError('Audit source, mask, render, or checkpoint PLY differs')
    if sha(source/'seed.ply')!=base['seed_sha256'] or sha(Path(base['command'][0]))!=base['binary_sha256']:raise ValueError('Original seed or trainer differs')
    lines=(source/'sparse/0/images.txt').read_text().splitlines();matches=[line.split() for line in lines if line.split() and line.split()[-1]==target]
    if len(matches)!=1 or matches[0][:-1]!=review['colmap_pose_row']:raise ValueError('Target pose differs from 7k audit')
    fields=matches[0];evalname='eval_'+target[len('train_'):];output.mkdir();(output/'INCOMPLETE').write_text('Diagnostic preparation incomplete\n');data=output/'data';(data/'images').mkdir(parents=True);(data/'masks').mkdir();(data/'sparse/0').mkdir(parents=True)
    for folder,src in (('images',image),('masks',mask)):
        os.link(src,data/folder/target);os.link(src,data/folder/evalname)
    os.link(source/'seed.ply',data/'seed.ply');os.link(source/'sparse/0/cameras.txt',data/'sparse/0/cameras.txt');(data/'sparse/0/points3D.txt').write_text('# diagnostic PLY initialization; no tracks\n');evalrow=fields.copy();evalrow[0]=str(int(fields[0])+1000000);evalrow[-1]=evalname;(data/'sparse/0/images.txt').write_text(' '.join(fields)+'\n\n'+' '.join(evalrow)+'\n\n')
    command=copy.deepcopy(base['command'])
    for flag,value in {'--data':str(data),'--output-dir-prefix':str(output),'--output-dir-name':'zero','--num-iterations':'0','--steps-per-save':'1','--save-full-checkpoint':'0'}.items():command[command.index(flag)+1]=value
    command+=['--init-ply',str(ply),'--init-ply-add-points','0','--save-only-latest-checkpoint','0','--use-bilateral-grid','0','--use-ppisp','0','--means-lr','0','--means-lr-final','0','--scales-lr','0','--scales-lr-final','0','--quats-lr','0','--opacities-lr','0','--projective-depth-lr','0','--projective-depth-lr-final','0','--noise-lr','0','--noise-lr-final','0','--opacity-reg','0','--scale-reg','0','--scale-regularization-weight','0','--refine-every','0','--max-screen-size','inf','--max-world-size','inf','--max-screen-size-penalty','0']
    fit=command.copy()
    for flag,value in {'--output-dir-name':'fit','--num-iterations':'500','--steps-per-save':'500'}.items():fit[fit.index(flag)+1]=value
    plan={'status':'prepared; zero-step parity required before fitting','method':'One observed training capture duplicated as a diagnostic evaluation view; no reconstruction or independent holdout claim. Raw appearance-grid-free initialization.','target':target,'target_source_sha256':sha(image),'target_mask_sha256':sha(mask),'target_pose_row':fields[:-1],'reference_render':str(ref),'reference_render_sha256':sha(ref),'source_manifest_sha256':sha(source_manifest),'audit_manifest_sha256':sha(audit_manifest),'source_ply':str(ply),'source_ply_sha256':sha(ply),'binary_sha256':sha(base['command'][0]),'zero_command':command,'fit_command':fit,'frozen':'means, scale, rotation, opacity, projective depth, noise; clipping and refinement disabled','budget':{'combined_output_bytes':160000000,'phase_timeout_seconds':120,'minimum_free_bytes':35*1024**3,'task_total_bytes':15000000000,'support_bytes':2000000000},'gate':'Zero-step target render must match saved raw 7k audit exactly; zero and fit PLY means, log-scales, quaternions, opacity must match bitwise.'}
    (output/'plan.json').write_text(json.dumps(plan,indent=2)+'\n');(output/'INCOMPLETE').unlink();return plan


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source_manifest','audit_manifest','ply','output'):p.add_argument(name,type=Path)
    p.add_argument('--target',default='train_001500_cam0.png');a=p.parse_args();plan=prepare(a.source_manifest,a.audit_manifest,a.ply,a.output,a.target);print(json.dumps({'target':plan['target'],'zero_command':plan['zero_command'],'fit_command':plan['fit_command']},indent=2))
if __name__=='__main__':main()
