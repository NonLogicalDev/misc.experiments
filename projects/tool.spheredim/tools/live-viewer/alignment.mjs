import * as THREE from 'three';
export function previewAdjustment(pitchDegrees,rollDegrees){
  if(!Number.isFinite(pitchDegrees)||!Number.isFinite(rollDegrees))throw Error('Invalid alignment angles');
  const pitch=new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1,0,0),THREE.MathUtils.degToRad(pitchDegrees));
  const roll=new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0,0,1),THREE.MathUtils.degToRad(rollDegrees));
  return roll.multiply(pitch).normalize();
}
export function gravityAlignment(up,pitch=0,roll=0){
  const q=Array.isArray(up)&&up.length===3&&up.every(Number.isFinite)&&Math.hypot(...up)>1e-8?new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(...up).normalize(),new THREE.Vector3(0,1,0)):new THREE.Quaternion();
  return q.premultiply(previewAdjustment(pitch,roll)).normalize();
}
export function gravityExport(up,pitch=0,roll=0){
  const q=gravityAlignment(up,pitch,roll),worldUp=new THREE.Vector3(0,1,0).applyQuaternion(q.clone().invert()).normalize();
  return {schema:'spheredim-gravity-v1',world_up:worldUp.toArray(),preview_quaternion_xyzw:q.toArray(),preview_axes:'Three.js +Y up',note:'world_up preserves corrected vertical; the preview quaternion includes a heading twist that a gravity-only alignment may not reproduce.'};
}
