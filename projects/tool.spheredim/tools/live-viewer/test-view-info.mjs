import assert from 'node:assert/strict';
import {serializeViewInfo} from './view-info.mjs';
const info={scene:{id:'dense-7000',label:'7,000-step continuation'},artifact:{run:'continuation',checkpoint:7000,version:'abc'},track:{index:12,source_frame:60,timestamp_seconds:2},camera:{coordinate_system:'Three.js world',position:[1,2,3],quaternion_xyzw:[0,0,0,1],up:[0,1,0],fov_degrees:55,aspect:2,near:.1,far:100},controls:{mode:'track',rotation:'turntable',view:'point',pivot_distance:1,target:[0,0,0]},alignment:{world_from_train:[[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]],scene_up:[0,0,1],correction_pitch_degrees:2,correction_roll_degrees:3,quaternion_xyzw:[0,0,0,1]},representation:'splat',viewport:{width_css_px:1000,height_css_px:500,dpr:2}};
const [heading,...body]=serializeViewInfo(info).split('\n');assert.equal(heading,'SphereDim view info (v1)');assert.deepEqual(JSON.parse(body.join('\n')),{schema:'spheredim-view-info-v1',...info});console.log('PASS view info serialization');
const {validateInitialView}=await import('./view-info.mjs');
const input={schema:'spheredim-view-info-v1',camera:{position:[1,2,3],quaternion_xyzw:[0,0,0,2],up:[0,1,0],fov_degrees:55,near:.1,far:1000},controls:{mode:'orbit',rotation:'turntable',view:'point',pivot_distance:1,target:[0,0,0]},representation:'splat'};
assert.deepEqual(validateInitialView(input).camera.quaternion_xyzw,[0,0,0,1]);
assert.equal(validateInitialView({...input,camera:{...input.camera,position:[NaN,0,0]}}),null);
assert.equal(validateInitialView({...input,controls:{...input.controls,view:'invalid'}}),null);
assert.equal(validateInitialView(null),null);

const {initialViewReady}=await import('./view-info.mjs');
assert.equal(initialViewReady(input,'orbit','turntable','point',0),true);
assert.equal(initialViewReady(input,'track','turntable','point',0),false);
const track={...input,controls:{...input.controls,mode:'track'},track:{index:4}};
assert.equal(initialViewReady(track,'track','turntable','point',3),false);
assert.equal(initialViewReady(track,'track','turntable','point',4),true);
assert.equal(validateInitialView({...track,track:{index:-1}}),null);

const {initialViewForPoseCount}=await import('./view-info.mjs');
assert.equal(initialViewForPoseCount(track,4),null);
assert.equal(initialViewForPoseCount(track,5),track);
assert.equal(initialViewForPoseCount(input,0),input);
