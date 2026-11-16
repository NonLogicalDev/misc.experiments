import assert from 'node:assert/strict';
import {splatDescription, trajectoryFilterNotice} from './quality.mjs';
assert.equal(splatDescription('saved/run', 'step-10000.ckpt'), 'Displayed splat: saved/run · step-10000.ckpt');
assert.equal(splatDescription('fallback/run', 'step-3000.ckpt'), 'Displayed splat: fallback/run · step-3000.ckpt');
assert.equal(splatDescription(null, null), null);
console.log('PASS displayed artifact description and trajectory notices');

assert.match(trajectoryFilterNotice({cutIndex:8,timeSeconds:8,reason:'speed'},false,10), /2 later positions hidden after a relative motion outlier at 8.0s/);
assert.match(trajectoryFilterNotice({cutIndex:100,timeSeconds:42.5,reason:'bounds'},false,101), /1 later position hidden after a position outlier at 42.5s/);
assert.equal(trajectoryFilterNotice({cutIndex:8,timeSeconds:8,reason:'speed'},true,10),null);
assert.equal(trajectoryFilterNotice(null,false,10),null);
assert.equal(trajectoryFilterNotice({cutIndex:10},false,10),null);
