#!/usr/bin/env python3
"""Compare fixed-plane source transfer with retained renders on source-selected ERP pixels."""
import argparse
import hashlib
import json
from pathlib import Path
import time
import cv2
import numpy as np
import compare_rigs as rig
import temporal_depth_roi as erp

W,H=2048,1024
NAMES=('eval_001440_cam0.png','eval_001500_cam0.png','eval_001560_cam0.png')


def inverse_plane_map(x,y,target_pose,source_pose,normal,d,width=W,height=H):
    """Map target pixel-center coordinates through a plane to the source ERP."""
    Rt,Ct=target_pose;Rs,Cs=source_pose
    ray=erp.rays(np.asarray(x)+.5,np.asarray(y)+.5,width,height)@Rt;den=ray@normal
    distance=-(Ct@normal+d)/np.where(np.abs(den)>1e-12,den,np.nan)
    valid=np.isfinite(distance)&(distance>0)
    world=Ct+ray*distance[:,None];sx,sy,source_range=erp.project(world,Rs,Cs,width,height)
    valid &= np.isfinite(sx)&np.isfinite(sy)&(source_range>1e-12)
    return sx-.5,sy-.5,valid


def bilinear_rgb(image,mask,x,y):
    """Read unchanged source RGB and require all four interpolation neighbors."""
    height,width=mask.shape;finite=np.isfinite(x)&np.isfinite(y);x=np.where(finite,x,0);y=np.where(finite,y,-1);floorx=np.floor(x);floory=np.floor(y);ix=floorx.astype(int)%width;iy=floory.astype(int);inside=finite&(iy>=0)&(iy+1<height)
    y0=np.clip(iy,0,height-1);y1=np.clip(iy+1,0,height-1);x1=(ix+1)%width
    valid=inside&(mask[y0,ix]==255)&(mask[y0,x1]==255)&(mask[y1,ix]==255)&(mask[y1,x1]==255)
    fx=(x-floorx)[:,None];fy=(y-floory)[:,None];a=image[y0,ix].astype(float)*(1-fx)+image[y0,x1].astype(float)*fx;b=image[y1,ix].astype(float)*(1-fx)+image[y1,x1].astype(float)*fx
    return (a*(1-fy)+b*fy),valid



def hull_support(shape, points):
    """Conservative source support: interpolation samples must remain inside this hull."""
    support=np.zeros(shape,np.uint8)
    if len(points)<3:raise ValueError('At least three inlier points required')
    hull=cv2.convexHull(np.asarray(points,np.float32)).reshape(-1,2)
    cv2.fillConvexPoly(support,np.rint(hull).astype(np.int32),255)
    return support


def metrics(reference,prediction,rows,height=H):
    error=np.mean((reference-prediction)**2,axis=1)/255**2;weight=np.sin(np.pi*(rows+.5)/height)
    return {'raw_mse':float(error.mean()),'spherical_mse':float(np.sum(error*weight)/np.sum(weight))}


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('data',type=Path);p.add_argument('zero',type=Path);p.add_argument('prior',type=Path);p.add_argument('footprint',type=Path);p.add_argument('output',type=Path);p.add_argument('--original-model',type=Path,required=True);p.add_argument('--neighbor-data',type=Path);p.add_argument('--neighbor-zero',type=Path);a=p.parse_args();start=time.monotonic()
    if bool(a.neighbor_data)!=bool(a.neighbor_zero):raise ValueError('Neighbor data and zero render must be supplied together')
    if a.output.exists():raise FileExistsError(a.output)
    prior=json.loads(a.prior.read_text());foot=json.loads(a.footprint.read_text());poses=rig.read_poses(a.data/'sparse/0');original_poses=rig.read_binary_poses(a.original_model/'images.bin');
    if digest(a.original_model/'images.bin')!=prior['model_sha256']['images.bin']:raise ValueError('Original model provenance mismatch')
    def verify_original_pose(name,pose):
        source_name='cam0/frame_'+name.split('_')[1]+'.png'
        if source_name not in original_poses or not all(np.allclose(x,y,rtol=0,atol=1e-8) for x,y in zip(pose,original_poses[source_name])):raise ValueError(f'Original gauge pose mismatch: {name}')
    for name in NAMES:verify_original_pose(name,poses[name])
    normal=np.array(prior['plan']['plane_normal']);d=prior['plan']['plane_d'];source_name=NAMES[1]
    source=cv2.imread(str(a.data/'images'/source_name));source_mask=cv2.imread(str(a.data/'masks'/source_name),0)
    if source is None or source.shape!=(H,W,3) or source_mask is None or source_mask.shape!=(H,W):raise ValueError('Invalid source')
    if digest(a.prior)!=foot['source_prior_sha256'] or digest(a.data/'sparse/0/images.txt')!=foot['pose_file_sha256']:raise ValueError('Prior or pose provenance mismatch')
    if len(set(foot['common_point_ids']))!=foot['common_count']:raise ValueError('Duplicate footprint IDs')
    zero_config=json.loads((a.zero/'config.json').read_text())
    if zero_config.get('eval_align') is not False or zero_config.get('use_ppisp') is not False or zero_config.get('use_bilateral_grid') is not False:raise ValueError('Expected unaligned appearance-off baseline')
    zero_poses=rig.read_poses(Path(zero_config['data'])/'sparse/0')
    for name in NAMES:
        if name not in zero_poses or not all(np.allclose(x,y,rtol=0,atol=1e-8) for x,y in zip(poses[name],zero_poses[name])):raise ValueError(f'Baseline pose mismatch: {name}')
    transform=json.loads((a.zero/'scene_transform.json').read_text())['train_from_world']['matrix_4x4']
    if not np.allclose(transform,np.eye(4),rtol=0,atol=1e-12):raise ValueError('Baseline scene gauge is not identity')
    for name in NAMES:
        if digest(a.data/'images'/name)!=foot['frames'][name]['source_sha256'] or digest(a.data/'masks'/name)!=foot['frames'][name]['mask_sha256']:raise ValueError('Source or mask hash mismatch')
    views=[(name,a.data,a.zero,i,foot['frames'][name]) for i,name in enumerate(NAMES)]
    if a.neighbor_data:
        neighbor_poses=rig.read_poses(a.neighbor_data/'sparse/0');neighbor_config=json.loads((a.neighbor_zero/'config.json').read_text());zero_neighbor_poses=rig.read_poses(Path(neighbor_config['data'])/'sparse/0')
        if neighbor_config.get('eval_align') is not False or neighbor_config.get('use_ppisp') is not False or neighbor_config.get('use_bilateral_grid') is not False:raise ValueError('Expected unaligned appearance-off neighbor baseline')
        if not np.allclose(json.loads((a.neighbor_zero/'scene_transform.json').read_text())['train_from_world']['matrix_4x4'],np.eye(4),rtol=0,atol=1e-12):raise ValueError('Neighbor scene gauge is not identity')
        plane_points=np.array([prior['accepted'][i]['xyz'] for i in foot['common_point_ids']])
        for name,index in [('eval_001495_cam0.png',0),('eval_001505_cam0.png',3)]:
            pose=neighbor_poses[name]
            verify_original_pose(name,pose)
            if name not in zero_neighbor_poses or not all(np.allclose(x,y,rtol=0,atol=1e-8) for x,y in zip(pose,zero_neighbor_poses[name])):raise ValueError('Neighbor pose mismatch')
            mask=cv2.imread(str(a.neighbor_data/'masks'/name),0)
            if mask is None or mask.shape!=(H,W):raise ValueError('Invalid neighbor mask')
            safe=cv2.erode((mask==255).astype(np.uint8),np.ones((5,5),np.uint8),borderType=cv2.BORDER_CONSTANT,borderValue=0);xx,yy,rr=erp.project(plane_points,*pose,W,H);ix=np.rint(xx).astype(int);iy=np.rint(yy).astype(int);valid=(ix>=0)&(ix<W)&(iy>=0)&(iy<H);ids=np.flatnonzero(valid);valid[ids]&=safe[iy[ids],ix[ids]]>0;coords=np.column_stack((xx[valid],yy[valid]))
            if not len(coords):raise ValueError('No neighbor projected footprint')
            lo=np.maximum(np.floor(coords.min(axis=0)).astype(int)-2,0);hi=np.minimum(np.ceil(coords.max(axis=0)).astype(int)+3,[W,H]);details={'projected_xy_native':coords.tolist(),'rect_xywh':[int(lo[0]),int(lo[1]),int(hi[0]-lo[0]),int(hi[1]-lo[1])]}
            poses[name]=pose;views.append((name,a.neighbor_data,a.neighbor_zero,index,details))
    a.output.mkdir(parents=True);results=[];display_images=[]
    landmarks=[r['xy'] for r in prior['plane_landmarks'] if r['inlier']]
    source_hull=hull_support((H,W),landmarks);display_source_mask=np.where((source_mask==255)&(source_hull==255),255,0).astype(np.uint8)
    for name,data,zero,i,footrow in views:
        if time.monotonic()-start>55:raise TimeoutError('CPU deadline')
        target=cv2.imread(str(data/'images'/name));mask=cv2.imread(str(data/'masks'/name),0);renderpath=zero/f'eval-render-{i:05d}.png';render=cv2.imread(str(renderpath));gt=cv2.imread(str(zero/f'eval-gt-{i:05d}.png'));savedmask=cv2.imread(str(zero/f'eval-mask-{i:05d}.png'),0)
        if any(x is None for x in (target,mask,render,gt,savedmask)) or target.shape!=(H,W,3) or render.shape!=target.shape or mask.shape!=(H,W):raise ValueError('Invalid target or saved render')
        if not np.array_equal(mask,savedmask) or np.max(np.abs(target.astype(np.int16)-gt.astype(np.int16)))>1:raise ValueError('Retained render source or mask mismatch')
        xyz=np.array(footrow['projected_xy_native']);coords=np.rint(xyz).astype(int);support=np.zeros((H,W),np.uint8)
        for x,y in coords:cv2.rectangle(support,(x-2,y-2),(x+2,y+2),1,-1)
        support &= (mask==255).astype(np.uint8);ys,xs=np.nonzero(support);sx,sy,valid=inverse_plane_map(xs,ys,poses[name],poses[source_name],normal,d);transfer,source_ok=bilinear_rgb(source,source_mask,sx,sy);valid &=source_ok
        if not valid.any():raise ValueError(f'No common source support: {name}')
        yy,xx=ys[valid],xs[valid];reference=target[yy,xx].astype(float);warped=transfer[valid];pred=render[yy,xx].astype(float)
        x,y,w,h=footrow['rect_xywh'];sample=np.zeros_like(target);sample[yy,xx]=np.clip(np.rint(warped),0,255).astype(np.uint8);header=np.zeros((24,3*w,3),np.uint8)
        for col,label in enumerate(('target source','plane transfer','original 7k')):cv2.putText(header,label,(col*w+3,16),cv2.FONT_HERSHEY_SIMPLEX,.35,(255,255,255),1,cv2.LINE_AA)
        # The transfer panel is black outside the scored support; the two other crops remain unaltered.
        sheet=a.output/(name[5:-4]+'.png');cv2.imwrite(str(sheet),np.vstack((header,np.hstack([im[y:y+h,x:x+w] for im in (target,sample,render)]))))
        # A separate display-only panel samples the assumed plane throughout the
        # measured source hull. It does not alter the sparse scoring support.
        gridy,gridx=np.indices((h,w));gridx=gridx.ravel()+x;gridy=gridy.ravel()+y
        ux,uy,plane_ok=inverse_plane_map(gridx,gridy,poses[name],poses[source_name],normal,d)
        display_values,display_ok=bilinear_rgb(source,display_source_mask,ux,uy)
        display_ok &= plane_ok & (mask[gridy,gridx]==255)
        continuous=np.zeros((h*w,3),np.uint8);continuous[display_ok]=np.clip(np.rint(display_values[display_ok]),0,255).astype(np.uint8);continuous=continuous.reshape(h,w,3)
        footprint_panel=target[y:y+h,x:x+w].copy();contours,_=cv2.findContours(support[y:y+h,x:x+w].copy(),cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE);cv2.drawContours(footprint_panel,contours,-1,(0,255,255),1)
        display_header=np.zeros((24,4*w,3),np.uint8)
        for col,label in enumerate(('source','assumed plane','original 7k','scored footprint')):cv2.putText(display_header,label,(col*w+2,16),cv2.FONT_HERSHEY_SIMPLEX,.32,(255,255,255),1,cv2.LINE_AA)
        display=np.vstack((display_header,np.hstack((target[y:y+h,x:x+w],continuous,render[y:y+h,x:x+w],footprint_panel))))
        ok,encoded=cv2.imencode('.png',display,[cv2.IMWRITE_PNG_COMPRESSION,9])
        if not ok:raise IOError('Could not encode display')
        display_path=a.output/(name[5:-4]+'-display.png');display_images.append((display_path,encoded.tobytes()))
        results.append({'display_path':str(display_path),'display_transfer_pixels':int(display_ok.sum()),'name':name,'candidate_footprint_pixels':len(xs),'common_valid_pixels':len(xx),'excluded_no_source_or_plane_support':int(len(xs)-len(xx)),'rect_xywh':[x,y,w,h],'source_transfer':metrics(reference,warped,yy),'original_7k':metrics(reference,pred,yy),'source_sha256':digest(data/'images'/name),'mask_sha256':digest(data/'masks'/name),'render_sha256':digest(renderpath),'sheet':str(sheet),'sheet_sha256':digest(sheet)})
    if sum(len(data) for _,data in display_images)>1_000_000:raise ValueError('Display-only images exceed 1 MB')
    for path,data in display_images:path.write_bytes(data)
    for row in results:row['display_sha256']=digest(Path(row['display_path']))
    report={'display_method':'Display-only continuous transfer uses the unchanged measured inlier source convex hull, source bilinear mask footprint and target mask, under the assumed plane. The yellow outline marks the unchanged sparse scoring support; display pixels are not added to metrics.','method':'Inverse source-ray intersection with fixed measured original-gauge poster plane. For raster array index (x,y), target rays use continuous ERP coordinates (x+0.5,y+0.5); projected source continuous coordinates are converted to array indices by subtracting 0.5. The original prior and footprint geometry remain unchanged; earlier SfM pixel convention uncertainty is not resolved by this raster convention. Common target support is the predeclared source-derived projected 5x5 point neighborhoods; all target mask and source bilinear interpolation masks must be valid. Transfer is a diagnostic resampling of unchanged source pixels, not new captured data; its panel is black outside scored support. No pose/depth/color fitting or image alignment. Mask validity does not rule out occlusion or moving content. 1500 was used to fit the plane; 1440/1560 only define evaluation footprint.','original_model_images_sha256':digest(a.original_model/'images.bin'),'original_sfm_manifest_sha256':digest(a.original_model.parents[2]/'manifest.json'),'pixel_convention_evidence':'Exporter panorama_direction uses column/row +0.5; original SfM run manifest records SS_SFM_PIXEL_CENTER=0. Existing prior geometry used integer ray inputs and is unchanged.','original_sfm_pixel_center_environment':json.loads((a.original_model.parents[2]/'manifest.json').read_text())['environment']['SS_SFM_PIXEL_CENTER'],'exporter_shader_sha256':digest(Path(__file__).resolve().parents[2]/'vendor/insta360-rs/work/src-rust/stitch_gpu.wgsl'),'source_footprint_pose_sha256':foot['pose_file_sha256'],'neighbor_pose_sha256':digest(a.neighbor_data/'sparse/0/images.txt') if a.neighbor_data else None,'prior_sha256':digest(a.prior),'footprint_sha256':digest(a.footprint),'poses_sha256':digest(a.data/'sparse/0/images.txt'),'script_sha256':digest(Path(__file__)),'results':results,'elapsed_seconds':time.monotonic()-start}
    (a.output/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    if sum(p.stat().st_size for p in a.output.iterdir() if p.is_file())>5000000:raise ValueError('Output exceeds 5 MB')
    print(json.dumps(results,indent=2))
if __name__=='__main__':main()
