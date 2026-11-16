import numpy as np
from native import rays
w,h=512,256
u=np.array([.1,128.,255.5,384.,511.9]);v=np.array([2.,64.,128.,192.,253.]);D=rays(u,v,w,h)
u2=np.mod(w/2+w/(2*np.pi)*np.arctan2(D[:,0],D[:,2]),w);v2=h/2+w/(2*np.pi)*np.arcsin(D[:,1]);du=np.minimum(abs(u-u2),w-abs(u-u2));assert np.max(du)<1e-9 and np.max(abs(v-v2))<1e-9
# Exact correspondences triangulate an analytically known plane.
C=np.array([0.,0.,0.]);C2=np.array([.16,0.,0.]);pts=np.array([[-1.,.5,4.],[0.,0.,4.],[1.,-.5,4.]])
a=pts-C;a/=np.linalg.norm(a,axis=1)[:,None];b=pts-C2;b/=np.linalg.norm(b,axis=1)[:,None];baseline=C2-C;dot=np.sum(a*b,axis=1);den=1-dot*dot;x=a@baseline;y=b@baseline;t1=(x-dot*y)/den;t2=(dot*x-y)/den;recon=((C+a*t1[:,None])+(C2+b*t2[:,None]))/2;err=np.max(np.linalg.norm(recon-pts,axis=1));assert err<1e-10
print('PASS equirectangular seam/pole rays and exact triangulation max_error',err)
