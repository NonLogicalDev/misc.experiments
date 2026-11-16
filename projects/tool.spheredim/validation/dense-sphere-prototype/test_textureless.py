import numpy as np
from epipolar import sweep
im=np.full((128,256,3),128,dtype=np.uint8);mask=np.full((128,256),255,dtype=np.uint8)
Rs=[np.eye(3)]*3;Cs=[np.array([x,0.,0.]) for x in (0,.2,.4)]
p,c,_=sweep([im,im,im],[mask,mask,mask],Rs,Cs,.1,.6,steps=32,stride=2)
print('textureless_result_points',len(p));assert len(p)==0
