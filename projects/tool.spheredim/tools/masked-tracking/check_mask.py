import numpy as np, torch
from types import SimpleNamespace
from dpvo import fastba
from dpvo.net import Patchifier
import masking
saved=[]
fastba.BA=lambda *args: saved.append(args[4].clone())
# Feature height=32; 53% threshold is row 18. Four observations: valid, mask band, black, target crossing.
coords=torch.tensor([[[[5.]*3]*3,[[25.]*3]*3],[[[5.]*3]*3,[[10.]*3]*3],[[[10.]*3]*3,[[25.]*3]*3],[[[6.]*3]*3,[[25.]*3]*3]]).unsqueeze(0)
fastba.reproject=lambda *args: coords
tracker=SimpleNamespace(network=SimpleNamespace(patchify=Patchifier()),device=torch.device('cpu'),counter=0,ht=128,wd=256,RES=4,n=0,tstamps_=torch.tensor([0]))
masking.install(tracker,.53)
frame=np.full((128,256,3),128,np.uint8);frame[100:104,40:44]=0
tracker.set_mask_frame(frame)
assert not tracker.network.patchify.allowed[(tracker.network.patchify.allowed[:,0]<18)].numel()
target=torch.tensor([[[5.,25.],[5.,10.],[10.,25.],[6.,10.]]]);weight=torch.ones(1,4,2); ids=torch.zeros(4,dtype=torch.long)
fastba.BA(None,None,None,target,weight,None,ids,ids,ids,0,1,1)
assert saved[0][0,:,0].tolist()==[1.,0.,0.,0.],saved
print('PASS source band, black pixel, projected-patch and predicted-target rejection')
