import {open,readdir} from 'node:fs/promises';
import path from 'node:path';
const C0=0.28209479177387814;
const clamp=x=>Math.max(0,Math.min(1,x));

// Spirula's splat checkpoint is binary little-endian with scalar float fields.
export function parseSplatHeader(buffer) {
  const end=buffer.indexOf(Buffer.from('end_header\n'));
  const win=buffer.indexOf(Buffer.from('end_header\r\n'));
  let idx=end>=0?end:win;if(idx<0)throw Error('Incomplete PLY header');
  const offset=idx+(idx===end?11:12),text=buffer.subarray(0,offset).toString('ascii'),lines=text.split(/\r?\n/);
  if(lines[0]!=='ply'||!lines.includes('format binary_little_endian 1.0'))throw Error('Unsupported PLY format');
  let vertex=false,count=null,properties=[],stride=0;
  for(const line of lines){const parts=line.trim().split(/\s+/);if(parts[0]==='element'){if(parts[1]==='vertex'){if(count!==null)throw Error('Multiple vertex elements');count=Number(parts[2]);vertex=true}else {if(count===null)throw Error('Non-vertex element before vertices');vertex=false}}else if(vertex&&parts[0]==='property'){if(parts[1]!=='float'&&parts[1]!=='float32')throw Error('Unsupported vertex field');properties.push(parts[2]);stride+=4}}
  if(!Number.isSafeInteger(count)||count<0||!['x','y','z','f_dc_0','f_dc_1','f_dc_2'].every(k=>properties.includes(k)))throw Error('Missing splat properties');
  if(new Set(properties).size!==properties.length)throw Error('Duplicate splat property');
  return {offset,count,stride,fields:['x','y','z','f_dc_0','f_dc_1','f_dc_2'].map(n=>properties.indexOf(n)*4)};
}
export async function readSplatCenters(file,cap=15000) {
  if(!Number.isSafeInteger(cap)||cap<1||cap>1000000)throw Error('Invalid point cap');
  if(path.basename(file)!=='splat.ply')throw Error('Only a completed splat.ply may be read');
  const f=await open(file,'r');try {
    const before=await f.stat();const header=Buffer.alloc(Math.min(before.size,1024*1024));let got=await f.read(header,0,header.length,0);const h=parseSplatHeader(header.subarray(0,got.bytesRead));
    if(h.count>(before.size-h.offset)/h.stride)throw Error('Incomplete PLY data');
    const step=Math.max(1,Math.ceil(h.count/cap)),vertices=[],colors=[];
    // Read contiguous blocks; do not allocate the entire potentially multi-GB checkpoint.
    const rows=Math.max(1,Math.floor(1024*1024/h.stride));let next=0;
    while(next<h.count){const first=next,last=Math.min(h.count,first+rows),data=Buffer.alloc((last-first)*h.stride),r=await f.read(data,0,data.length,h.offset+first*h.stride);if(r.bytesRead!==data.length)throw Error('Incomplete PLY data');
      while(next<last){let p=(next-first)*h.stride;let values=h.fields.map(k=>data.readFloatLE(p+k));if(values.every(Number.isFinite)){vertices.push(...values.slice(0,3));colors.push(...values.slice(3).map(x=>clamp(.5+C0*x)))}next+=step;}}
    const after=await f.stat();if(before.size!==after.size||before.mtimeMs!==after.mtimeMs)throw Error('Checkpoint changed while reading');
    return {vertices,colors,sourceCount:h.count,shownCount:vertices.length/3,label:'Gaussian centers, not splat rendering',file};
  } finally {await f.close()}
}
export async function latestSplatCenters(runDir,cap=15000){
  let entries;try{entries=await readdir(runDir,{withFileTypes:true})}catch{return null}
  const dirs=entries.filter(d=>d.isDirectory()&&/^step-\d+\.ckpt$/.test(d.name)).map(d=>d.name).sort().reverse();
  for(const d of dirs){try {const points=await readSplatCenters(path.join(runDir,d,'splat.ply'),cap);return {...points,checkpoint:d}}catch{/* incomplete, deleted, or not yet atomically published */}}
  return null;
}
