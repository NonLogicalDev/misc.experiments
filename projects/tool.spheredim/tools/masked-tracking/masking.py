"""Frame-specific black-pixel and conservative camera-relative operator exclusion."""
import inspect, math, textwrap, types
import cv2
import numpy as np
import torch
from dpvo import fastba
from dpvo.dpvo import autocast
import dpvo.net as net


def install(tracker, fraction):
    patcher = tracker.network.patchify
    masks = {}
    source = textwrap.dedent(inspect.getsource(type(patcher).forward))
    source = source.replace('self.__feature_gradient', 'self._Patchifier__feature_gradient')
    for count in ('3*patches_per_image', 'patches_per_image'):
        old = f'x = torch.randint(1, w-1, size=[n, {count}]).to(fmap.device)\n            y = torch.randint(1, h-1, size=[n, {count}]).to(fmap.device)'
        new = f'x, y = sample_valid(self, n, {count}, fmap.device)'
        if old not in source: raise RuntimeError('Unexpected upstream patch sampler')
        source = source.replace(old, new)
    def sample_valid(self, n, count, device):
        allowed = self.allowed
        if len(allowed) < count: raise RuntimeError('Too few valid patch locations')
        selected = allowed[torch.randint(0, len(allowed), (n,count), device=device)]
        return selected[...,1], selected[...,0]
    scope = dict(vars(net), sample_valid=sample_valid)
    exec(source, scope)
    patcher.forward = types.MethodType(scope['forward'], patcher)
    def set_frame(frame):
        h,w=frame.shape[:2]
        # Mark a feature cell invalid if it contains any nearly black source pixels.
        black=(frame.max(axis=2)<=3).astype(np.uint8)
        black=cv2.resize(black.astype(np.float32),(w//4,h//4),interpolation=cv2.INTER_AREA)>0
        black=cv2.dilate(black.astype(np.uint8),np.ones((3,3),np.uint8))>0
        black[:math.ceil((h//4)*fraction)+1,:]=True
        black[[0,-1],:]=True;black[:,[0,-1]]=True
        invalid=torch.from_numpy(black).to(tracker.device)
        masks[tracker.counter]=invalid
        patcher.allowed=torch.nonzero(~invalid)
    tracker.set_mask_frame=set_frame
    original_ba = fastba.BA
    def eligible(coords, target, jj):
        h,w = tracker.ht//tracker.RES, tracker.wd//tracker.RES
        indexes = tracker.tstamps_[:tracker.n+1].tolist()
        stack=torch.stack([masks[i] for i in indexes])
        def valid_at(x,y,indices):
            finite=torch.isfinite(x)&torch.isfinite(y)
            xx=torch.nan_to_num(x).round().long(); yy=torch.nan_to_num(y).round().long()
            within=(xx>=0)&(xx<w)&(yy>=0)&(yy<h)
            return finite & within & ~stack[indices,yy.clamp(0,h-1),xx.clamp(0,w-1)]
        projected=valid_at(coords[...,0,:,:],coords[...,1,:,:],jj[None,:,None,None]).all(dim=(-1,-2))
        predicted=valid_at(target[...,0],target[...,1],jj[None,:])
        return projected & predicted
    def masked_ba(poses, patches, intrinsics, target, weight, lmbda, ii, jj, kk, t0, t1, iterations):
        for _ in range(iterations):
            coords=fastba.reproject(poses, patches, intrinsics, ii, jj, kk)
            valid=eligible(coords,target,jj)
            original_ba(poses,patches,intrinsics,target,weight*valid[...,None],lmbda,ii,jj,kk,t0,t1,1)
    fastba.BA=masked_ba
    def motion_probe(self):
        kk=torch.arange(self.m-self.M,self.m,device=self.device)
        jj=self.n*torch.ones_like(kk);ii=self.ix[kk]
        hidden=torch.zeros(1,len(ii),self.DIM,**self.kwargs)
        coords=self.reproject(indicies=(ii,jj,kk))
        with autocast(self.device.type,enabled=False):
            corr=self.corr(coords,indicies=(kk,jj));ctx=self.imap[:,kk%(self.M*self.mem)]
            _,(delta,_,_)=self.network.update(hidden,ctx,corr,None,ii,jj,kk)
        valid=eligible(coords,coords[...,self.P//2,self.P//2]+delta.float(),jj)
        values=delta.norm(dim=-1).float()[valid]
        return torch.quantile(values,0.5) if values.numel() else torch.tensor(0.,device=self.device)
    tracker.motion_probe=types.MethodType(motion_probe,tracker)
