import assert from 'node:assert/strict';
import {mkdtemp,writeFile,rm,mkdir} from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {stateReader} from './state.mjs';
import {trajectoryFilterNotice} from './quality.mjs';
const dir=await mkdtemp(path.join(os.tmpdir(),'viewer-state-'));
try {
 const file=path.join(dir,'state.json');const reader=stateReader(file);
 assert.equal((await reader.snapshot()).configError,'Viewer state unavailable');
 const poses=Array.from({length:4},(_,i)=>({time_seconds:i*10,world_from_camera:[[1,0,0,i],[0,1,0,0],[0,0,1,0]]}));
 await writeFile(path.join(dir,'poses.json'),JSON.stringify({frames:poses}));
 await mkdir(path.join(dir,'other'));
 const ply=x=>`ply\nformat ascii 1.0\nelement vertex 1\nproperty float x\nproperty float y\nproperty float z\nend_header\n${x} 0 0\n`;await writeFile(path.join(dir,'dense.ply'),ply(1));await writeFile(path.join(dir,'other','dense.ply'),ply(2));
 await writeFile(path.join(dir,'a.log'),'first\n');await writeFile(path.join(dir,'b.log'),'second\n');
 const a={version:1,trajectory:{poses:'poses.json',filter:{cutIndex:1,timeSeconds:10,reason:'speed'}},artifacts:{dense:{file:'dense.ply'}},stages:[{name:'Mapping',status:'running',current:1,total:3}],currentActivity:0,logs:[{name:'Mapper',file:'a.log'}]};
 await writeFile(file,JSON.stringify(a));let s=await reader.snapshot();assert.equal(s.stages[0].name,'Mapping');assert.equal(s.currentActivity,0);assert.equal(s.logs[0].lines[0],'first');assert.equal(s.trajectory.length,3);assert.equal(s.densePoints.vertices[0],1);const version=s.denseVersion;await writeFile(path.join(dir,'dense.ply'),ply(123));s=await reader.snapshot();assert.equal(s.densePoints.vertices[0],123);assert.notEqual(s.denseVersion,version);assert.match(trajectoryFilterNotice(s.trajectoryFilter,false,s.cameraPoses.length),/10.0s/);
 const b={version:1,trajectory:{poses:'poses.json',filter:{cutIndex:3,timeSeconds:30,reason:'bounds'}},artifacts:{mesh:{file:'missing.ply'},dense:{file:'other/dense.ply'}},stages:[{name:'Meshing',status:'complete'}],logs:[{name:'Mesher',file:'b.log'}]};
 await writeFile(file,JSON.stringify(b));s=await reader.snapshot();assert.equal(s.stages[0].name,'Meshing');assert.equal(s.currentActivity,null);assert.equal(s.meshAvailable,false);assert.equal(s.densePoints.vertices[0],2);assert.equal(s.logs[0].lines[0],'second');assert.equal(s.trajectory.length,9);assert.match(trajectoryFilterNotice(s.trajectoryFilter,false,s.cameraPoses.length),/30.0s/);assert.equal(trajectoryFilterNotice(s.trajectoryFilter,true,s.cameraPoses.length),null);
 await writeFile(file,'{');assert.equal((await reader.snapshot()).stages[0].name,'Meshing');
 await writeFile(file,JSON.stringify({version:1}));s=await reader.snapshot();assert.equal(s.trajectoryFilter,null);assert.deepEqual(s.stages,[]);assert.deepEqual(s.logs,[]);
 console.log('PASS independent state fixtures, reload, missing and partial state');
} finally {await rm(dir,{recursive:true,force:true})}
