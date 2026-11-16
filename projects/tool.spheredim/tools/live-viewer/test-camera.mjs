import assert from 'node:assert/strict';
import * as THREE from 'three';
import {trackPose} from './camera.mjs';
const m=[[1,0,0,2],[0,1,0,3],[0,0,1,4]],p=trackPose(m);
assert.ok(new THREE.Vector3(0,0,-1).applyQuaternion(p.quaternion).distanceTo(new THREE.Vector3(0,0,1))<1e-8);
assert.ok(new THREE.Vector3(0,1,0).applyQuaternion(p.quaternion).distanceTo(new THREE.Vector3(0,-1,0))<1e-8);
assert.deepEqual(p.position.toArray(),[2,3,4]);
const q=trackPose(m,[0,0,1]);assert.ok(new THREE.Vector3(0,0,-1).applyQuaternion(q.quaternion).distanceTo(new THREE.Vector3(0,1,0))<1e-8);
assert.throws(()=>trackPose([[1]]));console.log('PASS tracked camera position, x-right/y-down/z-forward conversion and gravity');
