import assert from 'node:assert/strict';
import {reuseSceneData} from './scene-cache.mjs';
const previous={sceneId:'a',poseVersion:'same',pointsVersion:'same',cameraPoses:[],rawTrajectory:[],points:null};
const next={sceneId:'b',poseVersion:'same',pointsVersion:'same',cameraPoses:[1],rawTrajectory:[2],points:[3]};
assert.deepEqual(reuseSceneData(previous,{...next}),next);
const same=reuseSceneData({...previous,cameraPoses:[4],points:[5]},{...next,sceneId:'a'});
assert.deepEqual(same.cameraPoses,[4]); assert.deepEqual(same.points,[5]);
console.log('scene cache tests passed');

const {reconcileSceneChoice}=await import('./scene-cache.mjs');
const snapshot={sceneId:'a',scenes:[{id:'a'},{id:'b'}]};
assert.equal(reconcileSceneChoice('stale',snapshot),'a');
assert.equal(reconcileSceneChoice('b',snapshot),'b');
assert.equal(reconcileSceneChoice('',snapshot),'');
assert.equal(reconcileSceneChoice('b',{configError:'unknown'}),'b');
