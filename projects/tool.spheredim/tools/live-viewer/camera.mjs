import * as THREE from 'three';

// 360DVO camera coordinates x-right, y-down, z-forward; Three's camera
// coordinates x-right, y-up, -z-forward. Both transforms act on columns.
export function trackPose(matrix, up=null, correction=null) {
  if(!Array.isArray(matrix)||matrix.length!==3||!matrix.every(r=>Array.isArray(r)&&r.length===4&&r.every(Number.isFinite)))throw new Error('Invalid camera pose');
  const m=new THREE.Matrix4().set(...matrix[0],...matrix[1],...matrix[2],0,0,0,1);
  const conversion=new THREE.Matrix4().makeScale(1,-1,-1);
  const rot=new THREE.Quaternion().setFromRotationMatrix(m.multiply(conversion));
  const position=new THREE.Vector3(matrix[0][3],matrix[1][3],matrix[2][3]);
  if(up){const q=new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(...up).normalize(),new THREE.Vector3(0,1,0));position.applyQuaternion(q);rot.premultiply(q);}
  if(correction){position.applyQuaternion(correction);rot.premultiply(correction);}
  return {position,quaternion:rot};
}


// On first entry use the tracked orientation. Later frame changes move only
// position; alignment changes rotate the current look by the alignment delta.
export function updateTrackedCamera(camera,matrix,up,correction,previousAlignment=null){
  const base=Array.isArray(up)&&up.length===3&&up.every(Number.isFinite)&&Math.hypot(...up)>1e-8?new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(...up).normalize(),new THREE.Vector3(0,1,0)):new THREE.Quaternion();
  const alignment=base.premultiply(correction||new THREE.Quaternion()).normalize(),pose=trackPose(matrix,up,correction);
  camera.position.copy(pose.position);
  if(!previousAlignment)camera.quaternion.copy(pose.quaternion);
  else camera.quaternion.premultiply(alignment.clone().multiply(previousAlignment.clone().invert())).normalize();
  camera.updateMatrixWorld();return alignment;
}
