import assert from 'node:assert/strict';
import * as THREE from 'three';
import {trackPose,initialSceneFramer} from './camera.mjs';
const m=[[1,0,0,2],[0,1,0,3],[0,0,1,4]],p=trackPose(m);
assert.ok(new THREE.Vector3(0,0,-1).applyQuaternion(p.quaternion).distanceTo(new THREE.Vector3(0,0,1))<1e-8);
assert.ok(new THREE.Vector3(0,1,0).applyQuaternion(p.quaternion).distanceTo(new THREE.Vector3(0,-1,0))<1e-8);
assert.deepEqual(p.position.toArray(),[2,3,4]);
const q=trackPose(m,[0,0,1]);assert.ok(new THREE.Vector3(0,0,-1).applyQuaternion(q.quaternion).distanceTo(new THREE.Vector3(0,1,0))<1e-8);
assert.throws(()=>trackPose([[1]]));console.log('PASS tracked camera position, x-right/y-down/z-forward conversion and gravity');

const framer=initialSceneFramer(), identity=new THREE.Quaternion();
assert.equal(framer([],[],identity),null,'empty snapshot does not consume initial fit');
const values=[];for(let i=0;i<100;i++)values.push(i/100,i/200,0);values.push(100000,100000,100000);
const fit=framer(values,[0,0,0,1,1,0],identity);assert.ok(fit.size.x<2&&fit.size.y<2&&fit.size.z<1,'extreme outlier does not dictate framing');
assert.equal(framer([20,20,20],[10,10,10],identity),null,'later snapshots preserve user camera');
console.log('PASS robust initial scene fit and camera preservation');
