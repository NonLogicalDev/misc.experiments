"""Experimental spherical dense correspondence and triangulation, no view splitting."""
import numpy as np
import cv2


def rays(u,v,w,h):
    lon=(u-w/2)*(2*np.pi/w); lat=(h/2-v)*(2*np.pi/w)
    return np.stack([np.cos(lat)*np.sin(lon),-np.sin(lat),np.cos(lat)*np.cos(lon)],axis=-1)


def sample(img,x,y):
    return cv2.remap(img,x.astype('float32'),y.astype('float32'),cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT,borderValue=0)


def dense_pair(img1,img2,mask1,mask2,R1,C1,R2,C2,stride=2,min_angle=1.0,fb_max=1.0):
    h,w=img1.shape[:2]; assert img2.shape[:2]==(h,w)
    gray1=cv2.cvtColor(img1,cv2.COLOR_BGR2GRAY);gray2=cv2.cvtColor(img2,cv2.COLOR_BGR2GRAY)
    dis=cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    dis.setUseSpatialPropagation(True)
    flow12=dis.calc(gray1,gray2,None);flow21=dis.calc(gray2,gray1,None)
    u,v=np.meshgrid(np.arange(0,w,stride,dtype=np.float32),np.arange(0,h,stride,dtype=np.float32));flow=flow12[::stride,::stride];x=u+flow[:,:,0];y=v+flow[:,:,1]
    # Do not sample across ERP seam: reject seam-adjacent observations to avoid false matches.
    valid=(x>=2)&(x<w-2)&(y>=2)&(y<h-2)&(u>=2)&(u<w-2)&(mask1[::stride,::stride]>250)&(sample(mask2,x,y)>250)
    back=sample(flow21,x,y);valid &= np.linalg.norm(flow+back,axis=-1)<fb_max
    d1=rays(u,v,w,h)@R1.T;d2=rays(x,y,w,h)@R2.T;B=C2-C1;d=np.sum(d1*d2,axis=-1);den=1-d*d
    valid &= den>np.sin(np.deg2rad(min_angle))**2
    a=np.sum(d1*B,axis=-1);b=np.sum(d2*B,axis=-1);safe=np.where(den>1e-12,den,1)
    t1=(a-d*b)/safe;t2=(d*a-b)/safe;valid &= (t1>0)&(t2>0)&np.isfinite(t1)&np.isfinite(t2)
    p1=C1+d1*t1[:,:,None];p2=C2+d2*t2[:,:,None];depth=np.maximum(np.minimum(t1,t2),1e-6)
    valid &= np.linalg.norm(p1-p2,axis=-1)/depth<.01
    points=(p1+p2)*.5
    return {'points':points,'valid':valid,'colors':img1[::stride,::stride,::-1], 'flow':flow12,'x':x,'y':y,'depth':t1}


def consistent_cloud(imgs,masks,Rs,Cs,stride=2):
    """Keep points triangulated independently from source into two other frames."""
    first=dense_pair(imgs[0],imgs[1],masks[0],masks[1],Rs[0],Cs[0],Rs[1],Cs[1],stride)
    second=dense_pair(imgs[0],imgs[2],masks[0],masks[2],Rs[0],Cs[0],Rs[2],Cs[2],stride)
    depth=np.maximum(np.minimum(first['depth'],second['depth']),1e-6)
    valid=first['valid']&second['valid']&(np.abs(first['depth']-second['depth'])/depth<.05)
    pts=(first['points']+second['points'])*.5
    return pts[valid],first['colors'][valid],int(valid.sum()),int(first['valid'].sum()),int(second['valid'].sum())
