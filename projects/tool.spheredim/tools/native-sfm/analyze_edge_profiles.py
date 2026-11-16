#!/usr/bin/env python3
"""Compare fixed-image edge profiles inside a valid source mask; no alignment."""
import argparse
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np


def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def profiles(reference, rendered, mask, rect, radius=8, max_edges=600):
    if reference.shape != rendered.shape or reference.ndim != 2 or mask.shape != reference.shape:
        raise ValueError('Expected equal grayscale images and mask')
    x, y, w, h = rect
    height, width = reference.shape
    if min(x,y) < 0 or min(w,h) < 1 or x+w > width or y+h > height or radius < 2:
        raise ValueError('Invalid region or radius')
    gray = reference.astype(np.float32); pred = rendered.astype(np.float32)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3); gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    mag = np.hypot(gx,gy); edges = cv2.Canny(reference,50,150)>0
    valid = cv2.erode((mask==255).astype(np.uint8), np.ones((2*radius+3,2*radius+3),np.uint8), borderType=cv2.BORDER_CONSTANT,borderValue=0)>0
    region=np.zeros_like(valid);region[y:y+h,x:x+w]=True
    ys,xs=np.nonzero(edges & valid & region & (mag>80))
    if len(xs)>max_edges:
        take=np.linspace(0,len(xs)-1,max_edges,dtype=int);xs,ys=xs[take],ys[take]
    if not len(xs):raise ValueError('No valid source edges')
    norm=mag[ys,xs];nx=gx[ys,xs]/norm;ny=gy[ys,xs]/norm
    offsets=np.arange(-radius,radius+1,dtype=np.float32)
    mx=(xs[:,None]+nx[:,None]*offsets).astype(np.float32);my=(ys[:,None]+ny[:,None]*offsets).astype(np.float32)
    src=cv2.remap(gray,mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT)
    dst=cv2.remap(pred,mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT)
    # Prefer isolated, monotone source steps; use source alone to select them.
    contrast=src[:,-3:].mean(axis=1)-src[:,:3].mean(axis=1)
    deriv=np.diff(src,axis=1);positive=np.maximum(deriv,0).sum(axis=1);negative=np.maximum(-deriv,0).sum(axis=1)
    keep=(contrast>=20)&(positive>0)&(negative/(positive+1e-6)<0.4)
    src=src[keep];dst=dst[keep];xs=xs[keep];ys=ys[keep]
    if not len(xs):raise ValueError('No isolated source edges in region')
    def describe(values):
        d=np.maximum(np.diff(values,axis=1),0);mass=d.sum(axis=1);cdf=np.cumsum(d,axis=1)/np.maximum(mass[:,None],1e-6)
        mids=(offsets[:-1]+offsets[1:])/2
        q10=np.array([np.interp(.1,c,mids) for c in cdf]);q90=np.array([np.interp(.9,c,mids) for c in cdf])
        centroid=(d*mids).sum(axis=1)/np.maximum(mass,1e-6)
        contrast=values[:,-3:].mean(axis=1)-values[:,:3].mean(axis=1)
        return contrast,q90-q10,centroid
    sc,sw,sp=describe(src);rc,rw,rp=describe(dst)
    ok=(rc>0)&np.isfinite(rw)&np.isfinite(rp)
    if not ok.any():raise ValueError('No positive corresponding render profiles')
    def stats(values):
        return {'median':float(np.median(values)),'p10':float(np.percentile(values,10)),'p90':float(np.percentile(values,90))}
    return {'candidates':int(len(keep)),'source_selected':int(len(sc)),'positive_render_profiles':int(ok.sum()),
            'render_nonpositive_count':int((~ok).sum()),'source_contrast_8bit':stats(sc[ok]),'render_contrast_8bit':stats(rc[ok]),
            'contrast_ratio':stats(rc[ok]/sc[ok]),'source_width_10_90_px':stats(sw[ok]),'render_width_10_90_px':stats(rw[ok]),
            'signed_centroid_shift_px':stats(rp[ok]-sp[ok])}


def gradient_diagnostic(reference, rendered, mask, rect, shift_limit=4):
    """Measure signed gradient agreement and search a small diagnostic translation."""
    x,y,w,h=rect
    safe=cv2.erode((mask==255).astype(np.uint8),np.ones((2*shift_limit+5,2*shift_limit+5),np.uint8),borderType=cv2.BORDER_CONSTANT,borderValue=0)>0
    region=np.zeros_like(safe);region[y:y+h,x:x+w]=True;safe &= region
    ys,xs=np.nonzero(safe)
    if len(xs)<100:raise ValueError('Too few valid gradient pixels')
    a=reference.astype(np.float32);b=rendered.astype(np.float32)
    ax=cv2.Sobel(a,cv2.CV_32F,1,0,ksize=3);ay=cv2.Sobel(a,cv2.CV_32F,0,1,ksize=3)
    bx=cv2.Sobel(b,cv2.CV_32F,1,0,ksize=3);by=cv2.Sobel(b,cv2.CV_32F,0,1,ksize=3)
    av=np.stack((ax[ys,xs],ay[ys,xs]),axis=1);na=float(np.linalg.norm(av))
    if na==0:raise ValueError('No source gradient')
    def score(dx,dy):
        bv=np.stack((bx[ys+dy,xs+dx],by[ys+dy,xs+dx]),axis=1);nb=float(np.linalg.norm(bv))
        return float(np.sum(av*bv)/(na*nb)) if nb else 0.0
    bv=np.stack((bx[ys,xs],by[ys,xs]),axis=1);zero=score(0,0)
    best=max((score(dx,dy),dx,dy) for dy in range(-shift_limit,shift_limit+1) for dx in range(-shift_limit,shift_limit+1))
    return {'valid_pixels':len(xs),'render_to_source_gradient_rms':float(np.linalg.norm(bv)/na),
            'zero_shift_signed_gradient_correlation':zero,'best_integer_shift_px':[best[1],best[2]],
            'best_shift_signed_gradient_correlation':best[0],
            'note':'Diagnostic shift searches this crop only; metrics and displayed images remain unaligned. A high correlation can be dominated by large edges.'}


def analyze(audit, output, sheet):
    if output.exists() or sheet.exists():raise FileExistsError('Output exists')
    data=json.loads((audit/'audit.json').read_text()); rows={r['name']:r for r in data['frames']}
    regions=[('doorway','train_000930_cam0.png',[384,256,256,256]),('fabric','train_001005_cam0.png',[512,0,256,256]),('window blinds','train_001500_cam0.png',[640,128,256,256])]
    results=[];tiles=[]
    for label,name,rect in regions:
        i=rows[name]['index'];paths={kind:audit/'render'/f'eval-{kind}-{i:05d}.png' for kind in ('gt','mask','render')}
        imgs={kind:cv2.imread(str(path),cv2.IMREAD_GRAYSCALE if kind=='mask' else cv2.IMREAD_COLOR) for kind,path in paths.items()}
        if any(img is None for img in imgs.values()):raise ValueError(f'Missing {name}')
        if digest(paths['render'])!=rows[name]['render_sha256']:raise ValueError('Render hash mismatch')
        ref=cv2.cvtColor(imgs['gt'],cv2.COLOR_BGR2GRAY);pred=cv2.cvtColor(imgs['render'],cv2.COLOR_BGR2GRAY)
        metrics=profiles(ref,pred,imgs['mask'],rect);results.append({'region':label,'name':name,'rect_xywh':rect,'input_sha256':{k:digest(p) for k,p in paths.items()},'metrics':metrics,'gradient_diagnostic':gradient_diagnostic(ref,pred,imgs['mask'],rect)})
        x,y,w,h=rect;valid=imgs['mask'][y:y+h,x:x+w]==255;a=imgs['gt'][y:y+h,x:x+w].copy();b=imgs['render'][y:y+h,x:x+w].copy();a[~valid]=0;b[~valid]=0
        tile=np.concatenate((a,b),axis=1);cv2.rectangle(tile,(0,0),(2*w-1,22),(0,0,0),-1);cv2.putText(tile,label+' source / raw render',(3,15),cv2.FONT_HERSHEY_SIMPLEX,.42,(255,255,255),1,cv2.LINE_AA);tiles.append(tile)
    report={'method':'Fixed source-selected Canny/Sobel edges, eroded valid mask, straight 17-sample source-normal profiles. Source 8-bit grayscale contrast >=20 and low negative derivative select mostly isolated steps. Positive render contrast required for width/shift; rejected profiles counted. Width is 10–90% cumulative positive sampled gradient, signed displacement is centroid difference, contrast is end-window difference. No image alignment, optical PSF fitting or physical width claim; texture, multiple nearby edges, exposure and masks can confound. Render is raw without per-camera training appearance. Only three preselected regions; no independent pose truth.',
            'source_audit_sha256':digest(audit/'audit.json'),'analysis_script_sha256':digest(Path(__file__)),'regions':results}
    encoded=cv2.imencode('.png',np.concatenate(tiles,axis=0))[1].tobytes();raw=(json.dumps(report,indent=2,allow_nan=False)+'\n').encode()
    if len(encoded)+len(raw)>20*1024**2:raise RuntimeError('Output budget exceeded')
    with output.open('xb') as f:f.write(raw)
    with sheet.open('xb') as f:f.write(encoded)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('audit',type=Path);p.add_argument('output',type=Path);p.add_argument('sheet',type=Path);a=p.parse_args();print(json.dumps(analyze(a.audit,a.output,a.sheet)['regions'],indent=2))


if __name__=='__main__':main()
