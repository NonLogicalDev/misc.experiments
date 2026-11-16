import * as THREE from 'three';
// The cursor moves on a virtual hemisphere in camera coordinates. Composing
// incremental quaternions permits arbitrary pitch, yaw and roll without Euler
// angles, a pitch clamp, or an up-vector singularity.
export function arcballPoint(x,y,rect) {
  let a=2*(x-rect.left)/Math.max(rect.width,1)-1,b=1-2*(y-rect.top)/Math.max(rect.height,1),r=a*a+b*b;
  if(r>1){let k=1/Math.sqrt(r);return new THREE.Vector3(a*k,b*k,0)}
  return new THREE.Vector3(a,b,Math.sqrt(1-r));
}
export function arcballDelta(from,to) {return new THREE.Quaternion().setFromUnitVectors(to,from).normalize()}
export function composeFreeLook(orientation,from,to) {return orientation.clone().multiply(arcballDelta(from,to)).normalize()}
// Remove roll against +Y while keeping the current view direction. At an exact
// pole +Y cannot define roll, so retain the closest projected current up.
export function levelOrientation(orientation) {
  const q=orientation.clone().normalize(),forward=new THREE.Vector3(0,0,-1).applyQuaternion(q).normalize();
  let up=new THREE.Vector3(0,1,0);
  if(Math.abs(forward.dot(up))>.9999){up.set(0,1,0).applyQuaternion(q);up.addScaledVector(forward,-up.dot(forward));if(up.lengthSq()<1e-10){up.set(1,0,0).addScaledVector(forward,-forward.x)}up.normalize()}
  const m=new THREE.Matrix4().lookAt(new THREE.Vector3(),forward,up);
  return new THREE.Quaternion().setFromRotationMatrix(m).normalize();
}

// Turntable pitch remains on the upright side of both poles.
export function turntablePitch(orientation, delta) {
  const q=orientation.clone().normalize();
  const forward=new THREE.Vector3(0,0,-1).applyQuaternion(q);
  const pitch=Math.asin(THREE.MathUtils.clamp(forward.y,-1,1));
  const limit=Math.PI/2-1e-4;
  const next=THREE.MathUtils.clamp(pitch+delta,-limit,limit);
  return q.multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1,0,0),next-pitch)).normalize();
}
