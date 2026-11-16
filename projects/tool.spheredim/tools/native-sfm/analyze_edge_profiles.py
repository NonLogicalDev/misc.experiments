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


def scaled_rect(rect, shape):
    """Scale the fixed 1024x512 source regions to the input resolution."""
    height, width = shape
    if width < 128 or height < 64:
        raise ValueError('Image too small for fixed source regions')
    x, y, w, h = rect
    x0, x1 = round(x * width / 1024), round((x + w) * width / 1024)
    y0, y1 = round(y * height / 512), round((y + h) * height / 512)
    if min(x1-x0, y1-y0) < 32:
        raise ValueError('Scaled source region too small')
    return [x0, y0, x1-x0, y1-y0]


def frequency_diagnostic(reference, rendered, mask, rect):
    """Compare windowed, masked frequency coefficients without aligning images."""
    if reference.ndim != 2 or reference.shape != rendered.shape or mask.shape != reference.shape:
        raise ValueError('Expected equal grayscale images and mask')
    if not np.isfinite(reference).all() or not np.isfinite(rendered).all():
        raise ValueError('Non-finite image input')
    x, y, w, h = rect
    height, width = reference.shape
    if min(x, y) < 0 or min(w, h) < 32 or x+w > width or y+h > height:
        raise ValueError('Invalid or too-small region')
    valid = cv2.erode((mask == 255).astype(np.uint8), np.ones((5, 5), np.uint8),
                      borderType=cv2.BORDER_CONSTANT, borderValue=0)[y:y+h, x:x+w]
    window = np.outer(np.hanning(h), np.hanning(w)) * valid
    if np.count_nonzero(window) < 100 or window.sum() == 0:
        raise ValueError('Too few valid frequency pixels')
    src = reference[y:y+h, x:x+w].astype(np.float64)
    dst = rendered[y:y+h, x:x+w].astype(np.float64)
    if np.ptp(src[valid > 0]) == 0:
        raise ValueError('Constant source in valid region')
    # Remove each weighted mean before windowing to reduce mask-boundary leakage.
    def transform(image):
        return np.fft.rfft2((image - np.sum(image * window) / window.sum()) * window)
    a, b = transform(src), transform(dst)
    fy = np.fft.fftfreq(h)[:, None]
    fx = np.fft.rfftfreq(w)[None, :]
    freq = np.hypot(fx, fy)
    # rfft stores one half-plane; double non-DC/non-Nyquist columns for energy.
    weights = np.full(a.shape[1], 2.0)
    weights[0] = 1.0
    if w % 2 == 0:
        weights[-1] = 1.0
    bands = {}
    for label, lo, hi in [('1/32-1/8', 1/32, 1/8), ('1/8-1/4', 1/8, 1/4)]:
        selected = (freq >= lo) & (freq < hi)
        av, bv = a[selected], b[selected]
        weight = np.broadcast_to(weights, a.shape)[selected]
        ea = float(np.sum(weight * np.abs(av)**2))
        eb = float(np.sum(weight * np.abs(bv)**2))
        residual = float(np.sum(weight * np.abs(bv-av)**2))
        cross = float(np.sum(weight * np.real(av * np.conj(bv))))
        # Report absence explicitly rather than a misleading ratio.
        if ea <= 1e-12:
            bands[label] = {'status': 'no source energy'}
        else:
            bands[label] = {'status': 'ok', 'source_energy': ea,
                            'render_to_source_energy': eb/ea,
                            'residual_to_source_energy': residual/ea,
                            'coherence': cross/np.sqrt(ea*eb) if eb > 1e-12 else None,
                            'gain': cross/ea}
    return {'valid_pixels': int(valid.sum()), 'bands_cycles_per_pixel': bands,
            'note': 'Shared eroded source mask and Hann window; no alignment. Mask and window boundaries can leak energy across bands. Coherence is signed normalized coefficient agreement, gain is the signed source projection; neither alone proves faithful texture, pose, or optical blur.'}


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
        rect=scaled_rect(rect, ref.shape)
        metrics=profiles(ref,pred,imgs['mask'],rect);results.append({'region':label,'name':name,'rect_xywh':rect,'input_sha256':{k:digest(p) for k,p in paths.items()},'metrics':metrics,'gradient_diagnostic':gradient_diagnostic(ref,pred,imgs['mask'],rect),'frequency_diagnostic':frequency_diagnostic(ref,pred,imgs['mask'],rect)})
        x,y,w,h=rect;a=imgs['gt'][y:y+h,x:x+w];b=imgs['render'][y:y+h,x:x+w]
        heading=np.zeros((23,2*w,3),np.uint8);cv2.putText(heading,label+' source / raw render',(3,16),cv2.FONT_HERSHEY_SIMPLEX,.42,(255,255,255),1,cv2.LINE_AA)
        tiles.append(np.concatenate((heading,np.concatenate((a,b),axis=1)),axis=0))
    report={'method':'Fixed source-selected Canny/Sobel edges, eroded valid mask, straight 17-sample source-normal profiles. Source 8-bit grayscale contrast >=20 and low negative derivative select mostly isolated steps. Positive render contrast required for width/shift; rejected profiles counted. Width is 10–90% cumulative positive sampled gradient, signed displacement is centroid difference, contrast is end-window difference. No image alignment, optical PSF fitting or physical width claim; texture, multiple nearby edges, exposure and masks can confound. Render is raw without per-camera training appearance. Only three preselected regions; no independent pose truth.',
            'source_audit_sha256':digest(audit/'audit.json'),'analysis_script_sha256':digest(Path(__file__)),'regions':results}
    sheet_width=max(tile.shape[1] for tile in tiles)
    tiles=[cv2.copyMakeBorder(tile,0,0,0,sheet_width-tile.shape[1],cv2.BORDER_CONSTANT,value=0) for tile in tiles]
    encoded=cv2.imencode('.png',np.concatenate(tiles,axis=0))[1].tobytes();raw=(json.dumps(report,indent=2,allow_nan=False)+'\n').encode()
    if len(encoded)+len(raw)>5*1024**2:raise RuntimeError('Output budget exceeded')
    with output.open('xb') as f:f.write(raw)
    with sheet.open('xb') as f:f.write(encoded)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('audit',type=Path);p.add_argument('output',type=Path);p.add_argument('sheet',type=Path);a=p.parse_args();print(json.dumps(analyze(a.audit,a.output,a.sheet)['regions'],indent=2))


if __name__=='__main__':main()
