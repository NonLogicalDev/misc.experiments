import { readFile, open } from 'node:fs/promises';
import path from 'node:path';

export function parsePLY(text, cap = 15000) {
  const lines = text.split(/\r?\n/); let count = null, start = -1, props = [], vertex = false, ascii = false;
  for (let i = 0; i < lines.length; i++) {
    const s = lines[i].trim();
    if (s === 'format ascii 1.0') ascii = true;
    if (s.startsWith('element ')) { const a = s.split(/\s+/); vertex = a[1] === 'vertex'; if (vertex) count = Number(a[2]); }
    else if (vertex && s.startsWith('property ')) props.push(s.split(/\s+/).at(-1));
    if (s === 'end_header') { start = i + 1; break; }
  }
  if (!ascii || start < 0 || !Number.isSafeInteger(count) || count < 0 || !['x','y','z'].every(p => props.includes(p))) throw new Error('Incomplete or unsupported PLY');
  if (lines.length - start < count || lines.slice(start,start+count).some(line => !line.trim())) throw new Error('Incomplete PLY vertices');
  const indexes = ['x','y','z','red','green','blue'].map(p => props.indexOf(p));
  const vertices = [], colors = []; const step = Math.max(1, Math.ceil(count / cap));
  for (let i = 0; i < count; i += step) {
    const fields = lines[start + i].trim().split(/\s+/).map(Number);
    const point = indexes.slice(0,3).map(j => fields[j]);
    if (!point.every(Number.isFinite)) continue;
    vertices.push(...point);
    for (const j of indexes.slice(3)) colors.push(j < 0 || !Number.isFinite(fields[j]) ? .7 : Math.max(0, Math.min(1, fields[j]/255)));
  }
  return { vertices, colors, sourceCount: count, shownCount: vertices.length/3 };
}
async function maybeJson(file) { try { return JSON.parse(await readFile(file, 'utf8')); } catch { return null; } }
export async function readState({posesFile, pointsFile, trajectoryFilter} = {}, cap = 15000) {
  const poses = posesFile ? await maybeJson(posesFile) : null;
  const samples = [];
  if (Array.isArray(poses?.frames)) for (const frame of poses.frames) {
    const m=frame?.world_from_camera;
    if (Array.isArray(m) && m.length === 3 && m.every(r => Array.isArray(r) && r.length === 4 && r.every(Number.isFinite))) samples.push({point:[m[0][3],m[1][3],m[2][3]], matrix:m, time:frame.time_seconds, sourceFrame:frame.source_frame});
  }
  const rawTrajectory=samples.flatMap(s=>s.point);
  const cut=trajectoryFilter?.cutIndex;
  const filter=Number.isInteger(cut)&&cut>=0&&cut<samples.length?trajectoryFilter:null;
  let points=null; if(pointsFile)try {points=parsePLY(await readFile(pointsFile,'utf8'),cap)} catch {}
  return {trajectory:filter?rawTrajectory.slice(0,cut*3):rawTrajectory,rawTrajectory,trajectoryFilter:filter,cameraPoses:samples.map(s=>({matrix:s.matrix,timeSeconds:Number.isFinite(s.time)?s.time:null,sourceFrame:Number.isInteger(s.sourceFrame)?s.sourceFrame:null})),points};
}

// Read only the end of a configured local log; the client cannot choose paths.
export async function readLogTail(file, maxBytes = 32768, maxLines = 80) {
  if (!file) return [];
  let handle;
  try {
    handle = await open(file, 'r');
    const size = (await handle.stat()).size;
    const start = Math.max(0, size - maxBytes);
    const buffer = Buffer.alloc(size - start);
    const {bytesRead} = await handle.read(buffer, 0, buffer.length, start);
    const lines = buffer.subarray(0, bytesRead).toString('utf8').split(/\r?\n/);
    if (start > 0) lines.shift();
    if (lines.at(-1) === '') lines.pop();
    return lines.slice(-maxLines);
  } catch { return []; } finally { if (handle) await handle.close(); }
}
export async function readPipeline(file) { return file ? await maybeJson(file) : null; }
