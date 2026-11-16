import assert from 'node:assert/strict';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { parsePLY, readState, readLogTail, readPipeline } from './data.mjs';
import {filterTrajectory} from '../run-state/filter.mjs';
const ply='ply\nformat ascii 1.0\nelement vertex 3\nproperty float x\nproperty float y\nproperty float z\nproperty uchar red\nproperty uchar green\nproperty uchar blue\nend_header\n0 1 2 255 0 0\n1 2 3 0 255 0\n2 3 4 0 0 255\n';
assert.equal(parsePLY(ply,2).shownCount,2);
const samples=Array.from({length:10},(_,i)=>({point:[i<8?i:100+i,0,0],time:i}));
const filtered=filterTrajectory(samples);assert.equal(filtered.trajectoryFilter.cutIndex,8);assert.equal(filtered.trajectoryFilter.timeSeconds,8);assert.equal(filtered.trajectoryFilter.removedCount,2);assert.equal(filtered.trajectory.length,24);assert.equal(filtered.rawTrajectory.length,30);
assert.equal(filterTrajectory(samples.slice(0,5)).trajectoryFilter,null);
const bounded=Array.from({length:101},(_,i)=>({point:[i===100?100:Math.sin(i),0,0],time:i===100?42.5:null}));assert.equal(filterTrajectory(bounded).trajectoryFilter.reason,'bounds');assert.equal(filterTrajectory(bounded).trajectoryFilter.cutIndex,100);assert.equal(filterTrajectory(bounded).trajectoryFilter.timeSeconds,42.5);assert.equal(filterTrajectory(bounded).trajectoryFilter.removedCount,1);
assert.throws(()=>parsePLY(ply.replace('2 3 4 0 0 255\n','')));
let dir=await mkdtemp(path.join(os.tmpdir(),'spheredim-viewer-test-'));
try {
 let s=await readState();assert.equal(s.points,null);
 await writeFile(path.join(dir,'poses.json'),JSON.stringify({frames:[{world_from_camera:[[1,0,0,4],[0,1,0,5],[0,0,1,6]]}]}));
 await writeFile(path.join(dir,'sparse.ply'),ply);
 s=await readState({posesFile:path.join(dir,'poses.json'),pointsFile:path.join(dir,'sparse.ply')},2);assert.deepEqual(s.trajectory,[4,5,6]);assert.equal(s.points.shownCount,2);
 assert.deepEqual(await readLogTail(path.join(dir,'missing')),[]);
 await writeFile(path.join(dir,'stage.log'),'one\ntwo\nthree\n');
 assert.deepEqual(await readLogTail(path.join(dir,'stage.log'),100,2),['two','three']);
 assert.deepEqual(await readLogTail(path.join(dir,'stage.log'),8,80),['three']);
 assert.equal(await readPipeline(path.join(dir,'missing.json')),null);
 await writeFile(path.join(dir,'pipeline.json'),'{');assert.equal(await readPipeline(path.join(dir,'pipeline.json')),null);
 await writeFile(path.join(dir,'pipeline.json'),JSON.stringify({stage:'splat',iteration:3,total:10}));
 assert.equal((await readPipeline(path.join(dir,'pipeline.json'))).iteration,3);
 console.log('PASS snapshots, masks, pipeline progress and bounded log tail');
} finally {await rm(dir,{recursive:true,force:true})}
