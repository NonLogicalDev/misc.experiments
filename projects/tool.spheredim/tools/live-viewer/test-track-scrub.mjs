import assert from 'node:assert/strict';import * as THREE from 'three';import {updateTrackedCamera,finishTrackTransition} from './camera.mjs';import {previewAdjustment} from './alignment.mjs';
const camera=new THREE.PerspectiveCamera(),first=[[1,0,0,1],[0,1,0,2],[0,0,1,3]],second=[[0,-1,0,4],[1,0,0,5],[0,0,1,6]],identity=new THREE.Quaternion();let alignment=updateTrackedCamera(camera,first,null,identity);camera.quaternion.multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0,1,0),.73));const before=camera.quaternion.clone();alignment=updateTrackedCamera(camera,second,null,identity,alignment);assert.deepEqual(camera.position.toArray(),[4,5,6]);assert.ok(Math.abs(camera.quaternion.dot(before))>1-1e-12,'scrubbing preserves free-look quaternion despite different recorded rotation');const correction=previewAdjustment(10,0);alignment=updateTrackedCamera(camera,first,null,correction,alignment);assert.ok(Math.abs(camera.quaternion.dot(correction.clone().multiply(before)))>1-1e-12,'alignment rotates look consistently');console.log('PASS manual track scrubbing preserves look; alignment rotates it consistently');

// Entering and scrubbing Follow Track preserve the world look in both rotation modes.
for (const mode of ['free','turntable']) {
  const entry=new THREE.PerspectiveCamera(), rolled=new THREE.Matrix4().makeRotationZ(.7);
  entry.quaternion.setFromEuler(new THREE.Euler(.31,-.42,.27));
  const beforeEntry=entry.quaternion.clone(),e=rolled.elements;
  const pose=[[e[0],e[4],e[8],1],[e[1],e[5],e[9],2],[e[2],e[6],e[10],3]];
  let a=updateTrackedCamera(entry,pose,null,identity);finishTrackTransition(entry,mode,null,a);
  assert.ok(Math.abs(entry.quaternion.dot(beforeEntry))>1-1e-12,`${mode} entry preserves orientation`);
  assert.deepEqual(entry.position.toArray(),[1,2,3],`${mode} entry moves to track`);
  const look=entry.quaternion.clone(),prior=a;a=updateTrackedCamera(entry,second,null,identity,a);finishTrackTransition(entry,mode,prior,a);
  assert.ok(Math.abs(entry.quaternion.dot(look))>1-1e-12,`${mode} scrub preserves orientation`);
  assert.deepEqual(entry.position.toArray(),[4,5,6],`${mode} scrub moves to selected point`);
}
console.log('PASS track entry and scrubbing preserve free and turntable orientation');
