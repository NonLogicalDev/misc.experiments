import {readFile, readdir, stat} from 'node:fs/promises';
import path from 'node:path';

export async function latestSplat(runDir) {
  if (!runDir) return null;
  try {
    const entries=await readdir(runDir,{withFileTypes:true});
    const dirs=entries.filter(d=>d.isDirectory()&&/^step-\d+\.ckpt$/.test(d.name)).map(d=>d.name).sort().reverse();
    for (const dir of dirs) {
      const file=path.join(runDir,dir,'splat.ply');
      try {const s=await stat(file);if(s.isFile()&&s.size>0)return {file,version:dir};} catch {}
    }
  } catch {}
  return null;
}
export async function firstAvailable(...files) {
  for(const file of files)if(file)try{const info=await stat(file);if(info.isFile()&&info.size>0)return {file,info}}catch{}
  return null;
}
