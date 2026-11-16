import cv2,numpy as np
from native import rays
from epipolar import sweep
# A textured world plane at z=4, rendered analytically to full 2:1 panoramas.
w,h=512,256;v,u=np.meshgrid(np.arange(h),np.arange(w),indexing='ij');D=rays(u,v,w,h)
rng=np.random.default_rng(3);tex=rng.integers(0,256,size=(2048,2048,3),dtype=np.uint8);tex=cv2.GaussianBlur(tex,(15,15),3)
imgs=[];masks=[];Rs=[];Cs=[]
for x in (0,.16,.32):
 C=np.array([x,0.,0.]);t=(4-C[2])/np.maximum(D[:,:,2],1e-9);P=C+D*t[:,:,None];mx=(P[:,:,0]*100+1024).astype(np.float32);my=(P[:,:,1]*100+1024).astype(np.float32)
 valid=(D[:,:,2]>.35)&(mx>=3)&(mx<2045)&(my>=3)&(my<2045)
 image=cv2.remap(tex,mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT);image[~valid]=0
 imgs.append(image);masks.append((valid*255).astype(np.uint8));Rs.append(np.eye(3));Cs.append(C)
points,colors,cost=sweep(imgs,masks,Rs,Cs,.1,.6,steps=128,min_angle=1,stride=2)
n=len(points);assert n>20, f'not enough points: {n}'
err=np.abs(points[:,2]-4)/4
print('synthetic_plane points',n,'median_rel_depth_error',float(np.median(err)),'p95_rel_depth_error',float(np.percentile(err,95)))
assert np.median(err)<.05 and np.percentile(err,95)<.20
