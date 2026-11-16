import {readFile, stat} from 'node:fs/promises';
import path from 'node:path';
import {readState,parsePLY,readLogTail} from './data.mjs';

// Keep the last valid snapshot while a producer is replacing its state file.
export function stateReader(stateFile) {
 let last=null;
 const cache=new Map();
 async function cached(file,load){
  if(!file)return null;
  try{const info=await stat(file), key=`${info.dev}:${info.ino}:${info.size}:${info.mtimeMs}`;const old=cache.get(file);if(old?.key===key)return old.value;const value=await load();cache.set(file,{key,value});return value}catch{cache.delete(file);return null}
 }
 const base=stateFile?path.dirname(path.resolve(stateFile)):process.cwd();
 const resolve=p=>typeof p==='string'&&p?path.resolve(base,p):undefined;
 async function config(){try{const value=JSON.parse(await readFile(stateFile,'utf8'));if(value?.version!==1||typeof value!=='object'||Array.isArray(value))throw Error('Unsupported state');last=value}catch{} return last}
 function selectScene(c,id){
  const scenes=Array.isArray(c?.scenes)?c.scenes.filter(s=>s&&typeof s.id==='string'&&s.id&&typeof s.label==='string'):[];
  const chosen=id||c?.currentScene;
  return {scenes,selected:scenes.find(s=>s.id===chosen)};
 }
 async function loadScene(id){
  const c=await config();if(!c)throw Error('Viewer state unavailable');
  const {scenes,selected}=selectScene(c,id);
  if(Array.isArray(c.scenes)&&!selected)throw Error('Unknown scene');
  let scene=selected||c,sceneBase=base;
  if(selected?.stateFile){const file=resolve(selected.stateFile);sceneBase=path.dirname(file);scene=await cached(file,async()=>JSON.parse(await readFile(file,'utf8')));if(!scene||scene.version!==1)throw Error('Scene state unavailable');}
  const resolveScene=p=>typeof p==='string'&&p?path.resolve(sceneBase,p):undefined;
  return {c,scenes,selected,scene,resolveScene};
 }
 async function snapshot(id){
  let loaded;try{loaded=await loadScene(id)}catch(e){return {configError:e.message,trajectory:[],rawTrajectory:[],cameraPoses:[],points:null,stages:[],logs:[]}};
  const {scenes,selected,scene,resolveScene}=loaded;
  const posesFile=resolveScene(scene.trajectory?.poses),pointsFile=resolveScene(scene.trajectory?.points);
  const raw=await cached(posesFile,()=>readState({posesFile}));const points=await cached(pointsFile,async()=>parsePLY(await readFile(pointsFile,'utf8')));
  const data=raw?{...raw}:await readState();const cut=scene.trajectory?.filter?.cutIndex;data.trajectoryFilter=Number.isInteger(cut)&&cut>=0&&cut<data.cameraPoses.length?scene.trajectory.filter:null;data.trajectory=data.trajectoryFilter?data.rawTrajectory.slice(0,cut*3):data.rawTrajectory;data.points=points;data.poseVersion=cache.get(posesFile)?.key||null;data.pointsVersion=cache.get(pointsFile)?.key||null;data.trajectoryVersion=JSON.stringify([data.poseVersion,data.trajectoryFilter]);
  const a=scene.artifacts||{}, splat=resolveScene(a.splat?.file), mesh=resolveScene(a.mesh?.file), dense=resolveScene(a.dense?.file);
  const info=async f=>f?await stat(f).catch(()=>null):null;const [ss,ms,rs]=await Promise.all([info(splat),info(mesh),info(resolveScene(scene.reference?.file))]);
  data.splatAvailable=!!ss?.isFile();data.splatVersion=ss?`${ss.size}:${ss.mtimeMs}`:null;data.splatRun=a.splat?.run;data.splatCheckpoint=a.splat?.checkpoint;
  data.meshAvailable=!!ms?.isFile();data.meshVersion=ms?`${ms.size}:${ms.mtimeMs}`:null;data.densePoints=await cached(dense,async()=>parsePLY(await readFile(dense,'utf8')));data.denseVersion=cache.get(dense)?.key||null;
  data.denseLabel=a.dense?.label;data.denseSpace=a.dense?.space==='train'?'train':'world';data.worldFromTrain=null;
  try{const t=JSON.parse(await readFile(resolveScene(a.splat?.transform),'utf8'));const m=t?.world_from_train?.matrix_4x4;if(Array.isArray(m)&&m.length===4&&m.every(r=>Array.isArray(r)&&r.length===4&&r.every(Number.isFinite)))data.worldFromTrain=m}catch{}
  data.referenceVideoAvailable=!!rs?.isFile();data.referenceVideoLabel=scene.reference?.label;data.up=Array.isArray(scene.up)&&scene.up.length===3&&scene.up.every(Number.isFinite)?scene.up:null;data.sceneId=selected?.id||null;data.scenes=scenes.map(({id,label})=>({id,label}));
  data.stages=Array.isArray(scene.stages)?scene.stages:[];data.currentActivity=Number.isInteger(scene.currentActivity)?scene.currentActivity:null;data.logs=await Promise.all((Array.isArray(scene.logs)?scene.logs:[]).map(async l=>({name:l.name,lines:await readLogTail(resolveScene(l.file))})));data.details=Array.isArray(scene.details)?scene.details:[];
  return data;
 }
 return {config,snapshot,resolve,selectScene,loadScene};
}
