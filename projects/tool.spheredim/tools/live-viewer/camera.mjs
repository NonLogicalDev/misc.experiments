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

// Fit once when usable geometry first arrives. Later snapshots preserve manual view.
export function initialSceneFramer() {
  let done=false;
  return (points,trajectory,alignment) => {
    if(done)return null;
    const axes=[[],[],[]],p=new THREE.Vector3();
    for(const values of [points,trajectory])for(let i=0;values&&i+2<values.length;i+=3){
      p.set(values[i],values[i+1],values[i+2]).applyQuaternion(alignment);
      if(Number.isFinite(p.x)&&Number.isFinite(p.y)&&Number.isFinite(p.z)){axes[0].push(p.x);axes[1].push(p.y);axes[2].push(p.z)}
    }
    if(!axes[0].length)return null;
    const lower=[],upper=[];
    for(const axis of axes){axis.sort((a,b)=>a-b);lower.push(axis[Math.floor((axis.length-1)*.02)]);upper.push(axis[Math.ceil((axis.length-1)*.98)]);}
    const box=new THREE.Box3(new THREE.Vector3(...lower),new THREE.Vector3(...upper));
    done=true;return {center:box.getCenter(new THREE.Vector3()),size:box.getSize(new THREE.Vector3())};
  };
}
