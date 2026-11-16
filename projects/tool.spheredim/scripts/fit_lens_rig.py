"""Test a fixed stereo rig on spherical matches; distances use baseline units."""
import argparse,json
from pathlib import Path
import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation
from fit_static_lens_alignment import rays,summary


def epipolar(source,target,rotation,baseline):
    a=source@rotation.T
    scale=np.sqrt(np.sum(np.cross(baseline,a)**2,axis=1)+np.sum(np.cross(baseline,target)**2,axis=1))
    return np.einsum('ij,j->i',np.cross(target,a),baseline)/np.maximum(scale,1e-9)


def fit(source,target,initial_rotation):
    initial=np.r_[Rotation.from_matrix(initial_rotation).as_rotvec(),0.,0.]
    def unpack(v):
        t=np.array([1.,v[3],v[4]]);t/=np.linalg.norm(t)
        return Rotation.from_rotvec(v[:3]).as_matrix(),t
    def residual(v):
        R,t=unpack(v)
        return epipolar(source,target,R,t)
    bound=np.r_[np.full(3,np.deg2rad(4)),.2,.2]
    result=least_squares(residual,initial,bounds=(initial-bound,initial+bound),loss='soft_l1',f_scale=np.deg2rad(.08),max_nfev=400,xtol=1e-12,ftol=1e-12,gtol=1e-12)
    if not result.success:raise ValueError('Rig fit did not converge')
    return (*unpack(result.x),result)


def triangulate(source,target,rotation,baseline):
    a=source@rotation.T;b=target;c=np.sum(a*b,axis=1)
    denominator=1-c*c
    tb=b@baseline;ta=a@baseline
    d0=(tb-c*ta)/np.maximum(denominator,1e-12)
    d1=(c*tb-ta)/np.maximum(denominator,1e-12)
    p0=b*d0[:,None];p1=baseline+a*d1[:,None]
    valid=(denominator>1e-8)&(d0>0)&(d1>0)
    return (p0+p1)/2,valid,np.linalg.norm(p0-p1,axis=1)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('matches',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
    if a.output.exists():p.error('Output must be new')
    data=json.loads(a.matches.read_text());items=[]
    for f in data['frames']:items.append((f,rays(f['points1'],2048,1024),rays(f['points0'],2048,1024)))
    train=[x for x in items if x[0]['split']=='train']
    R,t,result=fit(np.concatenate([x[1] for x in train]),np.concatenate([x[2] for x in train]),np.array(data['rotation_matrix']))
    records=[]
    for f,source,target in items:
        residual=np.rad2deg(abs(epipolar(source,target,R,t)))
        points,valid,gap=triangulate(source,target,R,t)
        reliable=valid&(residual<.2)&(gap<.2)
        record={'frame':f['frame'],'split':f['split'],'epipolar_error_degrees':summary(residual),'positive_depth_count':int(valid.sum()),'reliable_count':int(reliable.sum()),'baseline_unit_distance_median':float(np.median(np.linalg.norm(points[reliable],axis=1))) if reliable.any() else None,'points_baseline_units':points.tolist(),'reliable':reliable.tolist()}
        records.append(record);print({k:v for k,v in record.items() if k not in ('points_baseline_units','reliable')})
    out={'mapping':'lens1 nominal ray -> common lens0 frame; lens1 origin = baseline_direction in baseline units','rotation_matrix':R.tolist(),'quaternion_xyzw':Rotation.from_matrix(R).as_quat().tolist(),'baseline_direction':t.tolist(),'optimizer_cost':result.cost,'frames':records}
    a.output.write_text(json.dumps(out,indent=2)+'\n');print('rotation xyzw',out['quaternion_xyzw'],'baseline',t)
if __name__=='__main__':main()
