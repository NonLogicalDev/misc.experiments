import {defineConfig} from 'vite';
import {createReadStream, readFileSync} from 'node:fs';
import path from 'node:path';
import {stat} from 'node:fs/promises';
import {stateReader} from './state.mjs';
const stateFile=process.env.SPHEREDIM_STATE;
const port=Number(process.env.SPHEREDIM_PORT||5178);
if(!Number.isSafeInteger(port)||port<1||port>65535)throw new Error('Invalid SPHEREDIM_PORT');
const reader=stateReader(stateFile);
function sendFile(res,file) {
  if(!file){res.statusCode=404;res.end('Not available');return;}
  res.setHeader('Content-Type','application/octet-stream');res.setHeader('Cache-Control','no-store');
  const stream=createReadStream(file);stream.on('error',()=>{if(!res.headersSent){res.statusCode=404;res.end('Not available');}else res.destroy();});stream.pipe(res);
}
async function sendReferenceVideo(req,res) {
  const referenceFile=reader.resolve((await reader.config())?.reference?.file);
  let size;try{if(!referenceFile)throw Error();const s=await stat(referenceFile);if(!s.isFile())throw Error();size=s.size}catch{res.statusCode=404;return res.end('Not available')}
  res.setHeader('Accept-Ranges','bytes');res.setHeader('Content-Type','video/mp4');res.setHeader('Cache-Control','no-store');
  let start=0,end=size-1;const range=req.headers.range;
  if(range){const match=/^bytes=(\d*)-(\d*)$/.exec(range);if(!match||(!match[1]&&!match[2])){res.statusCode=416;res.setHeader('Content-Range',`bytes */${size}`);return res.end()}
    if(!match[1]){const suffix=Number(match[2]);start=Math.max(0,size-suffix)}else {start=Number(match[1]);if(match[2])end=Math.min(end,Number(match[2]))}
    if(!Number.isSafeInteger(start)||!Number.isSafeInteger(end)||start>end||start>=size){res.statusCode=416;res.setHeader('Content-Range',`bytes */${size}`);return res.end()}
    res.statusCode=206;res.setHeader('Content-Range',`bytes ${start}-${end}/${size}`);
  }
  res.setHeader('Content-Length',Math.max(0,end-start+1));if(req.method==='HEAD'||size===0)return res.end();const stream=createReadStream(referenceFile,{start,end});stream.on('error',()=>res.destroy());stream.pipe(res);
}
export default defineConfig({server:{host:'127.0.0.1',port,strictPort:true},plugins:[{name:'local-reconstruction',configureServer(server){
  server.middlewares.use('/api/reference-video',(req,res)=>{sendReferenceVideo(req,res).catch(()=>{if(!res.headersSent){res.statusCode=500;res.end()}else res.destroy()})});
  server.middlewares.use('/api/state',async (_req,res)=>{try{const data=await reader.snapshot();res.setHeader('Content-Type','application/json');res.setHeader('Cache-Control','no-store');res.end(JSON.stringify(data))}catch(e){res.statusCode=500;res.end(JSON.stringify({error:String(e)}))}});
  server.middlewares.use('/api/splat.ply',async (_req,res)=>sendFile(res,reader.resolve((await reader.config())?.artifacts?.splat?.file)));
  server.middlewares.use('/api/mesh.ply',async (_req,res)=>sendFile(res,reader.resolve((await reader.config())?.artifacts?.mesh?.file)));
}}]});
