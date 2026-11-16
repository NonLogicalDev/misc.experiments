#!/usr/bin/env python3
"""Approximate native 3DGS alpha compositing at sampled ERP pixels, not GPU visibility."""
import argparse
import hashlib
import json
import time
from pathlib import Path
import cv2
import numpy as np
import compare_rigs

THRESHOLD = 1.0 / 255.0


def composite(alpha):
    """Input is front-to-back; mirror the rasterizer's alpha cutoff and early stop."""
    weights = np.zeros(len(alpha), dtype=float)
    transmittance = 1.0
    for i, value in enumerate(alpha):
        value = min(.999, float(value))
        if value <= THRESHOLD:
            continue
        next_t = transmittance * (1 - value)
        if next_t <= 1e-4:
            break
        weights[i] = transmittance * value
        transmittance = next_t
    return weights, transmittance


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def sh3(view, dc, rest):
    x, y, z = (view / np.linalg.norm(view, axis=1)[:, None]).T
    basis = np.column_stack((-0.48860251190292*y, 0.48860251190292*z, -0.48860251190292*x,
        1.092548430592079*x*y, -1.092548430592079*y*z, 0.9461746957575601*z*z-0.3153915652525201,
        -1.092548430592079*x*z, 0.5462742152960395*(x*x-y*y),
        -0.5900435899266435*(3*x*x*y-y*y*y), 2.890611442640554*x*y*z,
        (-2.285228997322329*z*z+0.4570457994644658)*y,
        z*(1.865881662950577*z*z-1.119528997770346),
        (-2.285228997322329*z*z+0.4570457994644658)*x,
        1.445305721320277*z*(x*x-y*y), -0.5900435899266435*(x*x*x-3*x*y*y)))
    return np.maximum(.5 + .2820947917738781*dc + np.einsum('nk,nck->nc',basis,rest),0)


def read_header(ply):
    with Path(ply).open('rb') as f:
        lines=[]
        while True:
            line=f.readline()
            if not line or len(lines)>1000:
                raise ValueError('Truncated or oversized PLY header')
            line=line.decode('ascii').strip();lines.append(line)
            if line=='end_header':break
        offset=f.tell()
    if lines[0]!='ply' or 'format binary_little_endian 1.0' not in lines:
        raise ValueError('Expected binary little-endian PLY')
    if sum(line.startswith('element ') for line in lines)!=1:
        raise ValueError('Expected only a vertex element')
    vertices=[line for line in lines if line.startswith('element vertex ')]
    if len(vertices)!=1:raise ValueError('Expected one vertex element')
    n=int(vertices[0].split()[-1]);properties=[line.split() for line in lines if line.startswith('property ')]
    if n<1 or any(len(x)!=3 or x[1]!='float' for x in properties):
        raise ValueError('Expected positive vertex count and scalar float properties')
    return n,[x[2] for x in properties],offset


def audit(ply, images_txt, image_name, mask_path, roi, grid, output, timeout, reference_render=None):
    start = time.monotonic()
    ply, images_txt, mask_path, output = map(Path, (ply, images_txt, mask_path, output))
    if output.exists():
        raise FileExistsError(output)
    mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
    if mask is None or mask.shape[1] != 2 * mask.shape[0]:
        raise ValueError('Expected a 2:1 ERP mask')
    height, width = mask.shape
    left, top, rw, rh = roi
    if grid < 1 or grid > 32 or min(left, top) < 0 or rw < 1 or rh < 1 or left + rw > width or top + rh > height:
        raise ValueError('Invalid ROI or sample grid')
    rows = [x.split() for x in images_txt.read_text().splitlines() if len(x.split()) == 10 and x.split()[-1] == image_name]
    if len(rows) != 1:
        raise ValueError('Expected one COLMAP pose')
    row = rows[0]
    R = compare_rigs.rotation(list(map(float, row[1:5])))
    t = np.array(list(map(float, row[5:8])))
    n, names, offset = read_header(ply)
    required = ['f_dc_0','f_dc_1','f_dc_2'] + [f'f_rest_{i}' for i in range(45)] + ['x', 'y', 'z', 'opacity'] + [f'scale_{i}' for i in range(3)] + [f'rot_{i}' for i in range(4)]
    if not set(required).issubset(names) or len(set(names)) != len(names) or ply.stat().st_size != offset + n * len(names) * 4:
        raise ValueError('Expected a standard all-float binary splat PLY')
    a = np.memmap(ply, dtype=np.dtype([(x, '<f4') for x in names]), mode='r', offset=offset, shape=(n,))
    cols = lambda fields: np.stack([a[x] for x in fields], axis=1).astype('float64')
    pos = cols(['x', 'y', 'z'])
    center = -R.T @ t
    dc = cols([f'f_dc_{i}' for i in range(3)])
    rest = cols([f'f_rest_{i}' for i in range(45)]).reshape(n,3,15)
    colors = sh3(pos-center, dc, rest)
    reference = cv2.imread(str(reference_render), cv2.IMREAD_COLOR) if reference_render else None
    if reference_render and (reference is None or reference.shape != (height,width,3)):
        raise ValueError('Reference render has wrong dimensions')
    q = cols([f'rot_{i}' for i in range(4)])
    scales = np.exp(cols([f'scale_{i}' for i in range(3)]))
    logits = a['opacity'].astype('float64')
    if not all(np.isfinite(v).all() for v in (pos, q, scales, logits)) or np.any(np.linalg.norm(q, axis=1) == 0):
        raise ValueError('Nonfinite splat or zero quaternion')
    q /= np.linalg.norm(q, axis=1)[:, None]
    w, x, y, z = q.T
    Q = np.stack([1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w), 2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w), 2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)], axis=-1).reshape(-1, 3, 3)
    v = pos @ R.T + t
    x, y, z = v.T
    h = np.hypot(x, z)
    r2 = np.sum(v*v, axis=1)
    eligible = (h > 1e-8) & (r2 > 1e-12)
    opacity = 1/(1+np.exp(-np.clip(logits,-80,80)))
    eligible &= opacity > THRESHOLD
    idx = np.flatnonzero(eligible)
    x, y, z, h, r2 = (v[idx] for v in (x, y, z, h, r2))
    u = width/(2*np.pi)*np.arctan2(x,z)+width/2
    vv = height/np.pi*np.arctan2(y,h)+height/2
    J = np.zeros((len(idx),2,3)); fx = width/(2*np.pi); fy = height/np.pi
    J[:,0,0]=fx*z/h**2; J[:,0,2]=-fx*x/h**2
    J[:,1,0]=-fy*x*y/(r2*h); J[:,1,1]=fy*h/r2; J[:,1,2]=-fy*z*y/(r2*h)
    A = np.einsum('nij,jk,nkl->nil', J, R, Q[idx]) * scales[idx,None,:]
    S = A @ A.transpose(0,2,1); S[:,0,0]+=.3; S[:,1,1]+=.3
    eig = np.linalg.eigvalsh(S); sig = np.sqrt(np.maximum(eig, 0)); det = S[:,0,0]*S[:,1,1]-S[:,0,1]*S[:,1,0]
    if np.any(det <= 0):
        raise ValueError('Invalid projected covariance')
    extent = np.minimum(3.33,np.sqrt(2*np.log(opacity[idx]/THRESHOLD)))
    rx=extent*np.sqrt(S[:,0,0]);ry=extent*np.sqrt(S[:,1,1])
    # Match projection's full-image AABB cull. Native ERP does not wrap this AABB.
    inside=(u+rx>0)&(u-rx<width)&(vv+ry>0)&(vv-ry<height)
    data=[]
    for gy in range(grid):
        for gx in range(grid):
            if time.monotonic()-start > timeout:
                raise TimeoutError('CPU audit time limit')
            px=left+int((gx+.5)*rw/grid);py=top+int((gy+.5)*rh/grid)
            if mask[py,px] != 255:
                continue
            xc,yc=px+.5,py+.5
            candidates=np.flatnonzero(inside & (u-rx<=xc)&(u+rx>=xc)&(vv-ry<=yc)&(vv+ry>=yc))
            dx=u[candidates]-xc;dy=vv[candidates]-yc;dd=det[candidates]
            sigma=.5*(S[candidates,1,1]*dx*dx+S[candidates,0,0]*dy*dy-2*S[candidates,0,1]*dx*dy)/dd
            keep=sigma>=0;candidates=candidates[keep];sigma=sigma[keep]
            alpha=np.minimum(.999,opacity[idx[candidates]]*np.exp(-sigma));order=np.argsort(r2[candidates],kind='stable');candidates=candidates[order];alpha=alpha[order]
            weights,T=composite(alpha);active=weights>0;weights=weights[active];candidates=candidates[active]
            if len(weights)==0:
                data.append({'pixel':[px,py],'layers':0,'alpha':0});continue
            total=weights.sum(); depths=np.sqrt(r2[candidates]);mean=(weights*depths).sum()/total
            k=int(np.argmax(weights));top_idx=int(idx[candidates[k]])
            cpu_rgb=np.clip(np.sum(weights[:,None]*colors[idx[candidates]],axis=0),0,1)
            observed=reference[py,px,::-1].astype(float)/255 if reference is not None else None
            data.append({'pixel':[px,py],'cpu_rgb':cpu_rgb.tolist(),'native_rgb':observed.tolist() if observed is not None else None,'layers':int(len(weights)),'effective_layers':float(total**2/np.sum(weights**2)), 'alpha':float(1-T),'weighted_minor_sigma_px':float(np.dot(weights,sig[candidates,0])/total),'weighted_major_sigma_px':float(np.dot(weights,sig[candidates,1])/total),'weight_fraction_major_ge_3px':float(weights[sig[candidates,1]>=3].sum()/total),'weight_fraction_major_ge_5px':float(weights[sig[candidates,1]>=5].sum()/total),'weighted_depth_mean':float(mean),'weighted_depth_std':float(np.sqrt(np.dot(weights,(depths-mean)**2)/total)),'dominant_weight_fraction':float(weights[k]/total),'dominant_splat_id':top_idx,'dominant_splat_opacity':float(opacity[top_idx]),'dominant_splat_minor_sigma_px':float(sig[candidates[k],0]),'dominant_splat_major_sigma_px':float(sig[candidates[k],1]),'dominant_splat_depth':float(depths[k])})
    valid=[x for x in data if x['layers']]
    if not valid:raise ValueError('No contributing rays')
    def quant(key):
        return [float(x) for x in np.percentile([v[key] for v in valid],[10,50,90])]
    result={'model_sha256':digest(ply),'pose_sha256':digest(images_txt),'mask_sha256':digest(mask_path),'camera_row':row,'roi_xywh':roi,'grid':grid,'total_splats':n,'eligible_projection':int(len(idx)),'valid_mask_rays':len(data),'rays_with_contributions':len(valid),'summary_p10_p50_p90':{k:quant(k) for k in ('layers','effective_layers','alpha','weighted_minor_sigma_px','weighted_major_sigma_px','weighted_depth_std','weight_fraction_major_ge_3px','weight_fraction_major_ge_5px','dominant_weight_fraction','dominant_splat_opacity','dominant_splat_minor_sigma_px','dominant_splat_major_sigma_px')},'elapsed_seconds':time.monotonic()-start,'limits':'CPU float64 approximation; exact GPU projection/tile intersections, sorting ties, culling and optical alpha not validated. ERP seam AABBs do not wrap. 3DGS center depths are radial and not surface intersections. Masked rays excluded.','rays':data}
    if reference is not None:
        delta=np.array([v['cpu_rgb'] for v in valid])-np.array([v['native_rgb'] for v in valid])
        result['rgb_comparison']={'sample_count':len(delta),'mae_8bit':float(np.abs(delta).mean()*255),'rmse_8bit':float(np.sqrt(np.mean(delta**2))*255),'max_abs_8bit':float(np.abs(delta).max()*255),'reference_sha256':digest(reference_render)}
    encoded = (json.dumps(result, indent=2, allow_nan=False) + '\n').encode()
    if len(encoded) > 1000000:
        raise ValueError('Report exceeds 1 MB')
    output.write_bytes(encoded)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for x in ('ply','images-txt','image-name','mask','output'):p.add_argument('--'+x,required=True)
    p.add_argument('--roi',nargs=4,type=int,required=True);p.add_argument('--grid',type=int,default=16);p.add_argument('--timeout',type=float,default=60)
    p.add_argument('--reference-render');a=p.parse_args();audit(a.ply,a.images_txt,a.image_name,a.mask,a.roi,a.grid,a.output,a.timeout,a.reference_render)

if __name__=='__main__':main()
