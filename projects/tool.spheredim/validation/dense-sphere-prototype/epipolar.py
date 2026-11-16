"""Native ERP plane-sweep multiview matching with known arbitrary-scale poses."""
import numpy as np, cv2
from native import rays

def sweep(imgs,masks,Rs,Cs,inv_lo,inv_hi,steps=128,min_angle=1.,stride=2):
 h,w=imgs[0].shape[:2];v,u=np.mgrid[0:h,0:w].astype(np.float32);r=rays(u,v,w,h).astype('float32')@Rs[0].astype('float32').T
 ref=cv2.cvtColor(imgs[0],cv2.COLOR_BGR2GRAY).astype('float32')/255
 kernel=(5,5);mean=cv2.boxFilter(ref,-1,kernel,normalize=True);var=np.maximum(cv2.boxFilter(ref*ref,-1,kernel,normalize=True)-mean*mean,0)
 # Costs are computed for every native ERP pixel: no cubemap or perspective faces.
 best=np.full((h,w),np.inf,np.float32);second=best.copy();bestinv=np.zeros((h,w),np.float32)
 targets=[cv2.cvtColor(im,cv2.COLOR_BGR2GRAY).astype('float32')/255 for im in imgs[1:]]
 safe_masks=[cv2.erode((mask>250).astype('uint8'),np.ones((7,7),np.uint8))*255 for mask in masks]
 for inv in np.linspace(inv_lo,inv_hi,steps,dtype=np.float32):
  P=Cs[0].astype('float32')+r/inv; costs=np.zeros((h,w),np.float32); ok=(safe_masks[0]>250)&(var>.00003)
  for j in range(len(targets)):
   Q=(P-Cs[j+1].astype('float32'))@Rs[j+1].astype('float32'); norm=np.linalg.norm(Q,axis=-1);x=np.mod(w/2+w/(2*np.pi)*np.arctan2(Q[:,:,0],Q[:,:,2]),w).astype('float32'); y=(h/2+w/(2*np.pi)*np.arcsin(np.clip(Q[:,:,1]/np.maximum(norm,1e-9),-1,1))).astype('float32')
   im=cv2.remap(targets[j],x,y,cv2.INTER_LINEAR,borderMode=cv2.BORDER_WRAP); m=cv2.remap(safe_masks[j+1],x,y,cv2.INTER_NEAREST,borderMode=cv2.BORDER_WRAP)
   mu=cv2.boxFilter(im,-1,kernel,normalize=True);vv=np.maximum(cv2.boxFilter(im*im,-1,kernel,normalize=True)-mu*mu,0);cov=cv2.boxFilter(ref*im,-1,kernel,normalize=True)-mean*mu
   cost=1-cov/np.sqrt(var*vv+1e-8);costs+=cost
   d2=(P-Cs[j+1].astype('float32'))/np.maximum(norm[:,:,None],1e-9);angle=np.arccos(np.clip(np.sum(r*d2,axis=-1),-1,1));ok &= (m>250)&(y>=2)&(y<h-2)&(angle>np.deg2rad(min_angle))
  costs=np.where(ok,costs,np.inf);improved=costs<best;second=np.minimum(second,np.where(improved,best,costs));best=np.where(improved,costs,best);bestinv=np.where(improved,inv,bestinv)
 valid=np.isfinite(best)&(best<.5)&(bestinv>inv_lo+1e-6)&(bestinv<inv_hi-1e-6)
 valid &= cv2.erode((masks[0]>250).astype('uint8'),np.ones((7,7),np.uint8))>0
 points=Cs[0]+r/np.maximum(bestinv[:,:,None],1e-9)
 vsub=valid[::stride,::stride];return points[::stride,::stride][vsub],imgs[0][::stride,::stride,::-1][vsub],best[::stride,::stride][vsub]
