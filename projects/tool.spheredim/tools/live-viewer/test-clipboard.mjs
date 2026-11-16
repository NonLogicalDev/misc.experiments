import assert from 'node:assert/strict';
import {copyText} from './clipboard.mjs';
function documentWith(result) { const field={style:{},setAttribute(){},focus(){},select(){},setSelectionRange(){},remove(){this.removed=true}}; const previousFocus={isConnected:true,focus(){this.restored=true}}; return {field,activeElement:previousFocus,previousFocus,body:{appendChild(){}},createElement(){return field},execCommand(){return result}}; }
let d=documentWith(true); assert.equal(await copyText('payload',d,undefined),true); assert.equal(d.field.removed,true); assert.equal(d.previousFocus.restored,true); assert.equal(d.field.style.fontSize,'16px');
d=documentWith(false); let copied=''; assert.equal(await copyText('payload',d,{writeText:async t=>{copied=t}}),true); assert.equal(copied,'payload');
d=documentWith(false); assert.equal(await copyText('payload',d,{writeText:async()=>{throw Error('denied')}}),false);
d=documentWith(false); assert.equal(await copyText('payload',d,undefined),false);
console.log('clipboard tests passed');
