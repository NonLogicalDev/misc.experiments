import assert from 'node:assert/strict';import * as THREE from 'three';import {composeFreeLook,levelOrientation,turntablePitch} from './rotation.mjs';
const from=new THREE.Vector3(0,0,1),a=Math.PI/40,to=new THREE.Vector3(0,Math.sin(a),Math.cos(a));let q=new THREE.Quaternion();for(let i=0;i<20;i++)q=composeFreeLook(q,from,to);const vertical=new THREE.Vector3(0,0,-1).applyQuaternion(q);assert.ok(Math.abs(vertical.y)>.999,'reaches vertical without locking');for(let i=0;i<20;i++)q=composeFreeLook(q,from,to);const beyond=new THREE.Vector3(0,0,-1).applyQuaternion(q);assert.ok(beyond.z>.999,'crosses the pole to the opposite direction');for(let i=0;i<40;i++)q=composeFreeLook(q,from,to);assert.ok(Math.abs(q.w)>.99999,'completes 360 degrees');const roll=composeFreeLook(new THREE.Quaternion(),new THREE.Vector3(1,0,0),new THREE.Vector3(0,1,0));assert.ok(Math.abs(new THREE.Vector3(1,0,0).applyQuaternion(roll).y)>.999,'can roll');console.log('PASS quaternion rotation across poles, 360 degrees and roll');

const rolled=new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0,0,1),1.1),level=levelOrientation(rolled);assert.ok(new THREE.Vector3(0,0,-1).applyQuaternion(rolled).distanceTo(new THREE.Vector3(0,0,-1).applyQuaternion(level))<1e-10);assert.ok(new THREE.Vector3(0,1,0).applyQuaternion(level).distanceTo(new THREE.Vector3(0,1,0))<1e-10);
for(const angle of [Math.PI/2,Math.PI/2-1e-8,Math.PI/2+1e-8]){const q=new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1,0,0),angle),out=levelOrientation(q);assert.ok(out.toArray().every(Number.isFinite));assert.ok(new THREE.Vector3(0,0,-1).applyQuaternion(q).distanceTo(new THREE.Vector3(0,0,-1).applyQuaternion(out))<1e-8)}console.log('PASS turntable roll removal and pole degeneracy');

let t=new THREE.Quaternion();
for(let i=0;i<200;i++)t=turntablePitch(t,.1);
let f=new THREE.Vector3(0,0,-1).applyQuaternion(t), u=new THREE.Vector3(0,1,0).applyQuaternion(t);
assert.ok(f.y>.99999 && f.y<1,'upward pitch stops before pole');
assert.ok(u.y>0,'upward drag keeps scene up');
for(let i=0;i<400;i++)t=turntablePitch(t,-.1);
f.set(0,0,-1).applyQuaternion(t);u.set(0,1,0).applyQuaternion(t);
assert.ok(f.y<-.99999 && f.y>-1,'downward pitch stops before pole');
assert.ok(u.y>0,'downward drag keeps scene up');
t=turntablePitch(t,.2);assert.ok(new THREE.Vector3(0,0,-1).applyQuaternion(t).y>-.999,'can move away from clamp');
console.log('PASS repeated turntable pitch stops at both poles');
