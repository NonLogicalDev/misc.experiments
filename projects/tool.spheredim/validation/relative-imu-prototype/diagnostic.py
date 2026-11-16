#!/usr/bin/env python3
"""Synthetic native ERP + relative orientation priors; CPU reference only.

Residuals are spherical ERP pixel coordinates and SO(3) relative rotations.
No perspective images are generated. IMU is simulated; units and covariance
are explicitly supplied and do not claim calibration for any real recording.
"""
import argparse,json,math
from pathlib import Path
import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation
from scipy.sparse import lil_matrix
p=argparse.ArgumentParser();p.add_argument('--output',required=True,type=Path);p.add_argument('--case',choices=('connected','weak-baseline','disconnected','wrong-imu','noisy-imu'),required=True);p.add_argument('--seed',type=int,default=31);p.add_argument('--max-evals',type=int,default=160);a=p.parse_args()
if a.output.exists():raise ValueError('output must be new')
a.output.mkdir(parents=True);rng=np.random.default_rng(a.seed);N=8;P=28;W,H=1024,512
baseline=.015 if a.case=='weak-baseline' else .28
C=np.array([[baseline*i,baseline*.35*np.sin(.7*i),baseline*.2*np.sin(.4*i)] for i in range(N)]);C-=C[0]
R=Rotation.from_rotvec(np.array([[.04*np.sin(i*.6),.035*np.sin(i*.4),.09*i] for i in range(N)]));R=R[0].inv()*R
xyz=rng.uniform([-2.5,-2,-2],[3,2,3],(P,3));xyz[:,2]+=2
# Evaluate the complete spherical camera. longitude is periodic.
def project(ray):
 x,y,z=ray;return np.array([((np.arctan2(x,z)/(2*np.pi)+.5)*W)%W,(np.arctan2(y,np.hypot(x,z))/np.pi+.5)*H])
obs=[]
for i in range(N):
 for j in range(P):
  if a.case=='disconnected' and ((i<4)!=(j<P//2)):continue
  uv=project(R[i].inv().apply(xyz[j]-C[i]))
  if uv[1]<H*.4 or uv[1]>=H*.98:continue
  uv+=rng.normal(0,.35,2)
  if rng.random()<.025:uv+=rng.normal(0,5,2)
  uv[0]%=W;obs.append((i,j,uv))
assert len(obs)>N*3
parents=list(range(N))
def find(i):
 while parents[i]!=i:parents[i]=parents[parents[i]];i=parents[i]
 return i
for j in range(P):
 views=[i for i,k,_ in obs if k==j]
 for i in views[1:]:parents[find(i)]=find(views[0])
visual_components=sorted([sum(find(i)==r for i in range(N)) for r in set(find(i) for i in range(N))],reverse=True)
# Construct simulated gyro relative rotations. Wrong IMU has a systematic
# increment bias; reported sigma remains tight to test a miscalibrated sensor.
imu=[];true_sigma=np.deg2rad(2.0 if a.case=='noisy-imu' else .2);claimed_sigma=np.deg2rad(.3)
for i in range(N-1):
 delta=R[i].inv()*R[i+1];noise=rng.normal(0,true_sigma,3)
 if a.case=='wrong-imu':noise+=np.deg2rad([0,0,4])
 imu.append(delta*Rotation.from_rotvec(noise))
# First camera is fixed (global SE3 gauge); known distance C0-C1 removes scale.
# Perturb remaining pose and points. Initial landmark estimates are truth plus
# noise; this isolates optimization, and is a favorable initialization.
C0=C+rng.normal(0,baseline*.08,(N,3));C0[0]=C[0];rv=(R*Rotation.from_rotvec(rng.normal(0,np.deg2rad(.8),(N,3)))).as_rotvec();rv[0]=R[0].as_rotvec();X0=xyz+rng.normal(0,.06,(P,3));r0=R[0];c0=C[0];x0=np.concatenate([np.column_stack((rv[1:],C0[1:])).ravel(),X0.ravel()]);gauge=np.linalg.norm(C[1]-C[0])
def unpack(v):
 cams=v[:6*(N-1)].reshape(N-1,6);rs=Rotation.from_rotvec(np.vstack((r0.as_rotvec(),cams[:,:3])));cs=np.vstack((c0,cams[:,3:]));pts=v[6*(N-1):].reshape(P,3);return rs,cs,pts
obs_i=np.array([i for i,_,_ in obs]);obs_j=np.array([j for _,j,_ in obs]);obs_uv=np.array([uv for _,_,uv in obs]);imuR=Rotation.concatenate(imu)
def residual(v,with_imu):
 rs,cs,pts=unpack(v)
 rays=rs[obs_i].inv().apply(pts[obs_j]-cs[obs_i]);x,y,z=rays.T
 u=(np.arctan2(x,z)/(2*np.pi)+.5)*W;v=(np.arctan2(y,np.hypot(x,z))/np.pi+.5)*H
 dx=(u-obs_uv[:,0]+W/2)%W-W/2;dy=v-obs_uv[:,1]
 out=[np.column_stack((dx/.35,dy/.35)).ravel(),np.array([(np.linalg.norm(cs[1]-cs[0])-gauge)/max(gauge*.005,1e-6)])]
 if with_imu:out.append((imuR.inv()*(rs[:-1].inv()*rs[1:])).as_rotvec().ravel()/claimed_sigma)
 return np.concatenate(out)
def sparsity(with_imu):
 M=2*len(obs)+1+(3*(N-1) if with_imu else 0);s=lil_matrix((M,len(x0)),dtype=np.int8)
 for k,(i,j,_) in enumerate(obs):
  if i:s[2*k:2*k+2,6*(i-1):6*i]=1
  s[2*k:2*k+2,6*(N-1)+3*j:6*(N-1)+3*j+3]=1
 s[2*len(obs),3:6]=1
 if with_imu:
  for i in range(N-1):
   row=2*len(obs)+1+3*i
   if i:s[row:row+3,6*(i-1):6*(i-1)+3]=1
   s[row:row+3,6*i:6*i+3]=1
 return s.tocsr()
def metrics(v):
 rs,cs,_=unpack(v);A=cs;B=C;ac=A.mean(0);bc=B.mean(0);X=A-ac;Y=B-bc;u,sv,vt=np.linalg.svd(Y.T@X/N);D=np.diag([1,1,np.linalg.det(u@vt)]);G=u@D@vt;den=np.mean(np.sum(X*X,axis=1));scale=np.trace(np.diag(sv)@D)/den;pos=np.linalg.norm((scale*(G@X.T)).T+bc-B,axis=1);angles=np.rad2deg((R.inv()*(Rotation.from_matrix(G)*rs)).magnitude());rel=np.rad2deg(((R[:-1].inv()*R[1:]).inv()*(rs[:-1].inv()*rs[1:])).magnitude());direct=np.rad2deg((R.inv()*rs).magnitude());return {'position_rms':float(np.sqrt(np.mean(pos**2))),'position_max':float(pos.max()),'rotation_median_deg':float(np.median(angles)),'rotation_p95_deg':float(np.percentile(angles,95)),'fixed_gauge_rotation_median_deg':float(np.median(direct)),'relative_rotation_truth_median_deg':float(np.median(rel)),'relative_rotation_truth_p95_deg':float(np.percentile(rel,95))}
# Finite-difference audit ensures jac_sparsity omits no observed dependence.
# It does not validate derivative magnitudes, convergence, or behavior at a seam.
def audit_sparsity(with_imu):
 pattern=sparsity(with_imu).tocsc();base=residual(x0,with_imu);worst=0.
 for col in range(len(x0)):
  v=x0.copy();v[col]+=1e-6;der=(residual(v,with_imu)-base)/1e-6
  allowed=np.zeros(len(base),dtype=bool);allowed[pattern.indices[pattern.indptr[col]:pattern.indptr[col+1]]]=True
  if (~allowed).any():worst=max(worst,float(np.max(np.abs(der[~allowed]))))
 return worst
jac_omissions=max(audit_sparsity(False),audit_sparsity(True))
if jac_omissions>1e-4:raise RuntimeError(f'Jacobian sparsity omits a dependence: {jac_omissions}')
results={'case':a.case,'seed':a.seed,'visual_component_sizes':visual_components,'jacobian_max_omitted_derivative':jac_omissions,'cameras':N,'points':P,'observations':len(obs),'first_camera_fixed':True,'scale_gauge':'known synthetic first baseline','imu_true_noise_sigma_deg':float(np.rad2deg(true_sigma)),'imu_claimed_sigma_deg':float(np.rad2deg(claimed_sigma)),'imu_bias_deg_per_edge':4 if a.case=='wrong-imu' else 0,'baseline_scale':baseline,'initial':metrics(x0)}
for enabled in (False,True):
 res=least_squares(residual,x0,args=(enabled,),jac_sparsity=sparsity(enabled),loss='huber',f_scale=2,tr_options={'atol':1e-10,'btol':1e-10,'maxiter':1000},max_nfev=a.max_evals,ftol=1e-6,xtol=1e-6,gtol=1e-6,verbose=0)
 vals=metrics(res.x);vals.update({'solver_success':bool(res.success),'solver_status':int(res.status),'message':str(res.message),'evaluations':res.nfev,'robust_cost':float(res.cost),'imu_relative_median_residual_deg':float(np.median([np.rad2deg((imu[i].inv()*(unpack(res.x)[0][i].inv()*unpack(res.x)[0][i+1])).magnitude()) for i in range(N-1)]))});results['visual_plus_imu' if enabled else 'visual_only']=vals
results['note']='Synthetic measurements, sampled scene and calibration. A disconnected visual graph still has unknown relative translation even with rotation links. Pose error uses one global similarity. Solver success alone is not a guarantee.'
(a.output/'metrics.json').write_text(json.dumps(results,indent=2)+'\n');print(json.dumps(results,indent=2))
