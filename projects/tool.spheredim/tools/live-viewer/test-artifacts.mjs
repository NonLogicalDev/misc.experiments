import assert from 'node:assert/strict';
import {mkdtemp,writeFile,rm} from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {firstAvailable} from '../run-state/artifacts.mjs';
const dir=await mkdtemp(path.join(os.tmpdir(),'artifact-test-'));try{const a=path.join(dir,'a'),b=path.join(dir,'b');await writeFile(b,'x');assert.equal((await firstAvailable(a,b)).file,b);await writeFile(a,'x');assert.equal((await firstAvailable(a,b)).file,a);console.log('PASS adapter artifact selection')}finally{await rm(dir,{recursive:true,force:true})}
