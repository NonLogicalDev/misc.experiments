"""Compare recorded X5 V6 projection interpretations on the same source pixels.

Candidate omnidirectional coefficients follow the independent Orbis hypothesis;
this module does not establish which interpretation describes this camera.
"""
import numpy as np
from scipy.spatial.transform import Rotation


def project_local(rays, lens, model):
    """Map lens-local unit rays to the recorded calibration canvas, in pixels."""
    rays=np.asarray(rays,dtype=float); den=rays[:,2]+lens['xi']*np.linalg.norm(rays,axis=1)
    x=rays[:,0]/den; y=rays[:,1]/den; x2=x*x; y2=y*y; xy=x*y; r2=x2+y2; r4=r2*r2
    k=np.asarray(lens['distortion_coefficients']); radial=1+k[0]*r2+k[1]*r4+k[2]*r4*r2+k[3]*r4*r4+k[4]*r4*r4*r2
    if model=='upstream':
        dx=x*radial+(k[5]+r2*k[7])*(r2+2*x2)+2*(k[6]+r2*k[8])*xy+k[9]*r2+k[11]*r4
        dy=y*radial+(k[6]+r2*k[8])*(r2+2*y2)+2*(k[5]+r2*k[7])*xy+k[10]*r2+k[12]*r4
    elif model=='thin_prism':
        radial -= k[4]*r4*r4*r2  # Slot 4 is reserved under this hypothesis.
        dx=x*radial+2*k[5]*xy+k[6]*(r2+2*x2)+k[7]*r2+k[8]*r4
        dy=y*radial+k[5]*(r2+2*y2)+2*k[6]*xy+k[9]*r2+k[10]*r4
    else: raise ValueError('unknown model')
    return np.column_stack((lens['cx']+lens['fx']*dx,lens['cy']+lens['fy']*dy))


def local_rays(theta,phi):
    return np.column_stack((np.sin(theta)*np.cos(phi),np.sin(theta)*np.sin(phi),np.cos(theta)))


def remap_rays(camera_rays, lens, source_model='upstream', target_model='thin_prism'):
    """Return target-model camera rays sampling identical source pixels, plus validity.

    The initial camera rays must be unit vectors inside the lens' supported field.
    Newton inversion uses each original ray as its initial guess; it fails closed on
    nonconvergence. Pixel residual is measured in the calibration canvas.
    """
    camera_rays=np.asarray(camera_rays,dtype=float); q=lens['orientation']; rot=Rotation.from_quat([q['x'],q['y'],q['z'],q['w']]); local=rot.apply(camera_rays)
    target=project_local(local,lens,source_model); theta=np.arccos(np.clip(local[:,2],-1,1));phi=np.arctan2(local[:,1],local[:,0]); eps=1e-6
    for _ in range(15):
        current=project_local(local_rays(theta,phi),lens,target_model);delta=target-current
        jt=(project_local(local_rays(theta+eps,phi),lens,target_model)-current)/eps
        jp=(project_local(local_rays(theta,phi+eps),lens,target_model)-current)/eps
        det=jt[:,0]*jp[:,1]-jt[:,1]*jp[:,0]; safe=np.abs(det)>1e-9
        dt=np.divide(delta[:,0]*jp[:,1]-delta[:,1]*jp[:,0],det,out=np.zeros_like(det),where=safe)
        dp=np.divide(jt[:,0]*delta[:,1]-jt[:,1]*delta[:,0],det,out=np.zeros_like(det),where=safe)
        theta+=np.clip(dt,-.1,.1);phi+=np.clip(dp,-.1,.1)
    rays=local_rays(theta,phi); residual=np.linalg.norm(project_local(rays,lens,target_model)-target,axis=1)
    valid=np.isfinite(residual)&(residual<.01)&(theta>=0)&(theta<=np.pi)
    return rot.inv().apply(rays),valid,residual
