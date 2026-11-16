// Adapt a legacy reconstruction's files into a generic, atomically published viewer state.
import {readFile, writeFile, rename} from 'node:fs/promises';
import path from 'node:path';
import {filterTrajectory} from './filter.mjs';
import {latestSplat,firstAvailable} from './artifacts.mjs';
const [source, destination, mode] = process.argv.slice(2);
if (!source || !destination) throw Error('Usage: node publish.mjs legacy.json viewer-state.json [--watch]');
const base=path.dirname(path.resolve(source));
const read=async p=>{try{return JSON.parse(await readFile(path.resolve(base,p),'utf8'))}catch{return null}};
const relative=p=>p?path.relative(path.dirname(path.resolve(destination)),path.resolve(base,p)):undefined;
async function publish(){
 const c=await read(path.resolve(source)); if(!c)throw Error('Cannot read source configuration');
 const tracking=c.tracking, progress=await read(path.join(tracking,'progress.json'));
 const posesName=['poses.json','poses-progress.json'].includes(progress?.poses_file)?progress.poses_file:'poses-progress.json';
 const pointsName=['sparse.ply','sparse-progress.ply'].includes(progress?.points_file)?progress.points_file:'sparse-progress.ply';
 const posesPath=path.join(tracking,posesName), poses=await read(posesPath), samples=[];
 for(const frame of poses?.frames||[]){const m=frame?.world_from_camera;if(Array.isArray(m)&&m.length===3&&m.every(r=>Array.isArray(r)&&r.length===4&&r.every(Number.isFinite)))samples.push({point:[m[0][3],m[1][3],m[2][3]],time:frame.time_seconds})}
 const filter=filterTrajectory(samples).trajectoryFilter;
 const extraStages=Array.isArray(c.extraStages)?c.extraStages.filter(s=>s&&typeof s.name==='string'&&typeof s.statusFile==='string').map(s=>[s.name,s.statusFile,s.logFile]):[];
 const stageSpecs=[...(Array.isArray(c.sceneProfiles)&&c.sceneProfiles.length?[]:extraStages),['Gaussian training',c.pipelineStatus,c.pipelineLog],['Splat comparison',c.splatComparisonStatus,c.splatComparisonLog],['Mask comparison',c.maskComparisonStatus,c.maskComparisonLog],['Full-frame 360 SfM',c.fullSfmStatus,c.fullSfmLog],['Earlier 360 SfM',c.sfmStatus,c.sfmLog]];
 const stages=[];const logs=[];
 for(const [name,statusFile,log] of stageSpecs){const d=statusFile&&await read(statusFile);if(d){const metrics=[];if(name==='Earlier 360 SfM'&&log){try{const tail=(await readFile(path.resolve(base,log),'utf8')).match(/Components:\s*(\d+),\s*covering\s*(\d+)\/(\d+)\s+distinct images/i);if(tail){metrics.push({label:'Images covered',value:`${tail[2]} / ${tail[3]}`},{label:'Models',value:tail[1]})}}catch{}}stages.push({name,status:d.partial?'partial':d.status,detail:[d.stage,d.arm].filter(Boolean).join(' · '),current:d.current??d.iteration??d.done,total:d.total,etaSeconds:d.eta_seconds,error:d.error,metrics})}if(log)logs.push({name,file:relative(log)})}
 const primary=await latestSplat(path.resolve(base,c.splatRun)); const fallback=c.splatFallbackRun&&await latestSplat(path.resolve(base,c.splatFallbackRun)); const splat=primary||fallback; const run=primary?c.splatRun:c.splatFallbackRun;
 const dense=await firstAvailable(c.denseFile&&path.resolve(base,c.denseFile),c.denseFallbackFile&&path.resolve(base,c.denseFallbackFile)); const mesh=await firstAvailable(c.meshFile&&path.resolve(base,c.meshFile),c.meshFallbackFile&&path.resolve(base,c.meshFallbackFile));
 let currentActivity=stages.findIndex(stage=>stage.status==='running');if(currentActivity<0)currentActivity=stages.findIndex(stage=>['blocked','paused'].includes(stage.status));if(currentActivity<0&&stages.length)currentActivity=0;
 const state={version:1,currentActivity:currentActivity>=0?currentActivity:null,trajectory:{poses:relative(posesPath),points:relative(path.join(tracking,pointsName)),filter},artifacts:{splat:splat?{file:relative(splat.file),transform:relative(path.join(run,'scene_transform.json')),run,checkpoint:splat.version}:null,dense:{file:dense&&relative(dense.file),label:c.denseLabel,space:c.denseSpace},mesh:{file:mesh&&relative(mesh.file)}},reference:{file:relative(c.referenceVideo),label:c.referenceLabel},up:c.up,stages,logs};
 // A scene profile is an independent coordinate system; never inherit its artifacts from the previous scene.
 const profiles=Array.isArray(c.sceneProfiles)?c.sceneProfiles:[];
 const scenes=[{id:'previous',label:c.previousSceneLabel||'Previous reconstruction',trajectory:state.trajectory,artifacts:state.artifacts,up:state.up,stages:state.stages,currentActivity:state.currentActivity,logs:state.logs,details:state.details}];
 for(const spec of profiles){
  if(!spec||typeof spec.id!=='string'||!spec.id||spec.id==='previous'||typeof spec.label!=='string'||typeof spec.stateFile!=='string'||scenes.some(x=>x.id===spec.id))continue;
  const file=path.resolve(base,spec.stateFile),profile=await read(file);if(!profile||profile.version!==1||!profile.trajectory)continue;
  const rebase=value=>typeof value==='string'&&value?path.relative(path.dirname(path.resolve(destination)),path.resolve(path.dirname(file),value)):undefined;
  const rebaseArtifact=value=>value&&typeof value==='object'?{...value,file:rebase(value.file),transform:rebase(value.transform)}:null;
  const a=profile.artifacts||{};
  scenes.push({id:spec.id,label:spec.label,trajectory:{poses:rebase(profile.trajectory.poses),points:rebase(profile.trajectory.points),filter:profile.trajectory.filter},artifacts:{splat:rebaseArtifact(a.splat),dense:rebaseArtifact(a.dense),mesh:rebaseArtifact(a.mesh)},up:profile.up,stages:profile.stages||[],currentActivity:profile.currentActivity??null,logs:(profile.logs||[]).map(l=>({...l,file:rebase(l.file)})),details:profile.details||[]});
 }
 if(scenes.length>1){state.scenes=scenes;state.currentScene=scenes.some(x=>x.id===c.currentScene)?c.currentScene:'previous';}
 const tmp=destination+'.tmp';await writeFile(tmp,JSON.stringify(state,null,2)+'\n');await rename(tmp,destination);
}
await publish(); if(mode==='--watch')setInterval(()=>publish().catch(e=>console.error(e)),2000);
