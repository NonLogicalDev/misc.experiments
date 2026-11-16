#!/usr/bin/env python3
"""Synthetic 360DVO-style native ERP bundle adjustment diagnostic.

Truth and observations are generated analytically on the sphere. No images or
perspective views are constructed. Pose/point noise and false feature matches
are seeded. Use of truth-perturbed 3D initialization is a controlled favorable
condition, not a complete real-data reconstruction pipeline.
"""
import argparse,collections,json,math,sys
from pathlib import Path
import numpy as np,pycolmap as p
parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);parser.add_argument('--outlier-fraction',type=float,default=.03);parser.add_argument('--pixel-noise',type=float,default=.25);parser.add_argument('--pose-noise-deg',type=float,default=.5);parser.add_argument('--seed',type=int,default=341);parser.add_argument('--local-track-length',type=int,default=0,help='limit each track to a consecutive visible window');parser.add_argument('--triangulate-initial',action='store_true');parser.add_argument('--baseline-scale',type=float,default=1.0);parser.add_argument('--disconnect-graph',action='store_true');args=parser.parse_args()
assert not args.output.exists();args.output.mkdir(parents=True);modeldir=args.output/'input';modeldir.mkdir();rng=np.random.default_rng(args.seed);N=32;P=600;W,H=1024,512;camera=p.Camera(model='EQUIRECTANGULAR',width=W,height=H,params=[W,H])
def rot(v):
 angle=np.linalg.norm(v)
 if angle<1e-12:return np.eye(3)
 x,y,z=v/angle;K=np.array([[0,-z,y],[z,0,-x],[-y,x,0]])
 return np.eye(3)+np.sin(angle)*K+(1-np.cos(angle))*(K@K)
def qfrom(M):
 # Stable matrix to quaternion via pycolmap
 q=p.Rotation3d(M).quat;return [q[3],q[0],q[1],q[2]]
truth=[];initial=[]
for i in range(N):
 t=2*np.pi*i/N;center=args.baseline_scale*np.array([1.8*np.cos(t),1.2*np.sin(t),.55*np.sin(2*t)]);R=rot(np.array([.18*np.sin(t),.2*np.cos(2*t),t*.55]));truth.append((R,center));initial.append((rot(rng.normal(0,np.deg2rad(args.pose_noise_deg),3))@R,center+rng.normal(0,.025,3)))
# Points occupy a 3D volume around the trajectory, including both hemispheres.
points=rng.uniform([-5,-5,-3],[5,5,4],(P,3));candidate={};total_outliers=0
for j,pt in enumerate(points):
 obs=[]
 for i,(R,C) in enumerate(truth):
  v=R.T@(pt-C);uv=camera.img_from_cam(v,check_cheirality=False)
  if uv is None or not (.4*H+4 <= uv[1]<.97*H):continue
  uv=uv+rng.normal(0,args.pixel_noise,2)
  if rng.random()<args.outlier_fraction:uv+=rng.normal(0,8,2);total_outliers+=1
  uv[0]%=W;obs.append((i,uv))
 if args.disconnect_graph:
  side=int(rng.integers(0,2));obs=[o for o in obs if (o[0]>=N//2)==bool(side)]
 if len(obs)>=3:
  if args.local_track_length:
   size=min(args.local_track_length,len(obs));start=int(rng.integers(0,len(obs)-size+1));obs=obs[start:start+size]
  candidate[j]=obs
# Reserve 20% of entire 3D tracks for independent pose evaluation.
allids=np.array(sorted(candidate));held=set(map(int,rng.choice(allids,size=len(allids)//5,replace=False)));train=[j for j in allids if j not in held];perim=[[] for _ in range(N)];tracks={};initial_points={};dropped=0
for j in list(train):
 if not args.triangulate_initial:initial_points[j]=points[j]+rng.normal(0,.05,3);continue
 mats=[];rhs=[];items=[]
 for i,uv in candidate[j]:
  R,C=initial[i];d=R@camera.cam_ray_from_img(uv);Q=np.eye(3)-np.outer(d,d);mats.append(Q);rhs.append(Q@C);items.append((C,d))
 A=np.sum(mats,axis=0)
 if np.linalg.cond(A)>1e6:train.remove(j);dropped+=1;continue
 x=np.linalg.solve(A,np.sum(rhs,axis=0))
 if any(np.dot(x-C,d)<=0 for C,d in items):train.remove(j);dropped+=1;continue
 initial_points[j]=x

for j in train:
 track=[]
 for i,uv in candidate[j]:
  track.append((i+1,len(perim[i])));perim[i].append((uv,j+1))
 tracks[j]=track
parent=list(range(N))
def find(x):
 while parent[x]!=x:parent[x]=parent[parent[x]];x=parent[x]
 return x
for j in train:
 ids=[i for i,_ in candidate[j]]
 for i in ids[1:]:parent[find(i)]=find(ids[0])
components=sorted(collections.Counter(find(i) for i in range(N)).values(),reverse=True)
(modeldir/'cameras.txt').write_text(f'1 EQUIRECTANGULAR {W} {H} {W} {H}\n')
with (modeldir/'images.txt').open('w') as f:
 for i,(R,C) in enumerate(initial):
  Rwc=R.T;t=-Rwc@C;q=qfrom(Rwc);f.write(' '.join(map(str,[i+1,*q,*t,1,f'frame_{i:03d}.png']))+'\n');f.write(' '.join(f'{uv[0]} {uv[1]} {pid}' for uv,pid in perim[i])+'\n')
with (modeldir/'points3D.txt').open('w') as f:
 for j in train:
  x=initial_points[j];f.write(' '.join(map(str,[j+1,*x,127,127,127,0]))+' '+' '.join(f'{im} {ix}' for im,ix in tracks[j])+'\n')
r=p.Reconstruction(modeldir);assert len(r.images)==N and len(r.points3D)==len(train)
def solve_error(model,poses_truth):
 ids=sorted(model.images);A=np.array([model.images[i].projection_center() for i in ids]);B=np.array([poses_truth[i-1][1] for i in ids]);a=A.mean(0);b=B.mean(0);X=A-a;Y=B-b;u,s,vt=np.linalg.svd(Y.T@X/len(A));S=np.diag([1,1,np.linalg.det(u@vt)]);R=u@S@vt;scale=np.trace(np.diag(s)@S)/np.mean(np.sum(X*X,axis=1));aligned=(scale*(R@X.T)).T+b;pos=np.linalg.norm(aligned-B,axis=1);angs=[]
 for id in ids:
  Rc=model.images[id].cam_from_world().rotation.matrix().T;Rt=poses_truth[id-1][0];angs.append(np.degrees(np.arccos(np.clip((np.trace(Rt.T@R@Rc)-1)/2,-1,1))))
 return {'position_rms':float(np.sqrt(np.mean(pos**2))),'position_max':float(max(pos)),'rotation_median_degrees':float(np.median(angs)),'rotation_p95_degrees':float(np.percentile(angs,95))}
def heldout_error(model):
 e=[];kept=0
 for j in held:
  obs=candidate[j];blocks=[];vec=[];data=[]
  for i,uv in obs:
   im=model.images[i+1];D=im.cam_from_world().rotation.matrix().T@camera.cam_ray_from_img(uv);C=im.projection_center();A=np.eye(3)-np.outer(D,D);blocks.append(A);vec.append(A@C);data.append((im,uv,C,D))
  mat=np.sum(blocks,axis=0)
  if np.linalg.cond(mat)>1e5:continue
  X=np.linalg.solve(mat,np.sum(vec,axis=0))
  if any(np.dot(X-C,D)<=0 for _,_,C,D in data):continue
  for im,uv,_,_ in data:
   z=camera.img_from_cam(im.cam_from_world()*X,check_cheirality=False)
   if z is None:continue
   dx=(z[0]-uv[0]+W/2)%W-W/2;e.append(float(np.hypot(dx,z[1]-uv[1])))
  kept+=1
 return {'tracks':kept,'observations':len(e),'mean_px':float(np.mean(e)),'median_px':float(np.median(e)),'p95_px':float(np.percentile(e,95))}
coverage=[len(x) for x in perim];before=solve_error(r,truth);before_held=heldout_error(r)
opts=p.BundleAdjustmentOptions();opts.refine_focal_length=False;opts.refine_principal_point=False;opts.refine_extra_params=False;opts.ceres.loss_function_type=p.LossFunctionType.HUBER;opts.ceres.loss_function_scale=2.;opts.ceres.solver_options.max_num_iterations=100;opts.ceres.solver_options.num_threads=4
cfg=p.BundleAdjustmentConfig()
for i in r.images:cfg.add_image(i)
cfg.fix_gauge(p.BundleAdjustmentGauge.TWO_CAMS_FROM_WORLD)
summary=p.create_default_bundle_adjuster(opts,cfg,r).solve();assert np.array_equal(r.cameras[1].params,[W,H]);after=solve_error(r,truth);after_held=heldout_error(r);out=args.output/'optimized';out.mkdir();r.write(out)
result={'graph_components':components,'initialization':'triangulated' if args.triangulate_initial else 'truth-perturbed','dropped_initial_tracks':dropped,'baseline_scale':args.baseline_scale,'disconnect_graph':args.disconnect_graph,'seed':args.seed,'cameras':N,'scene_points':P,'training_tracks':len(train),'heldout_tracks':len(held),'mask_top_fraction':.4,'local_track_length':args.local_track_length,'pixel_noise_sigma':args.pixel_noise,'outlier_fraction':args.outlier_fraction,'generated_outlier_observations':total_outliers,'initial_pose_rotation_noise_sigma_degrees':args.pose_noise_deg,'initial_position_noise_sigma':.025,'initial_point_noise_sigma':.05,'min_training_observations_per_frame':min(coverage),'pose_before':before,'pose_after':after,'heldout_before':before_held,'heldout_after':after_held,'termination':str(summary.termination_type),'note':'Heldout tracks fit their own 3D positions and never entered BA; pose truth is independent synthetic ground truth. Noise, masks and track selection are synthetic.'}
(args.output/'metrics.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
