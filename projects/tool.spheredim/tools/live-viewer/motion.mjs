import * as THREE from 'three';
export function movementDirection(forward,cameraUp,keys){
 const right=new THREE.Vector3().crossVectors(forward,cameraUp).normalize(),v=new THREE.Vector3();
 if(keys.has('w'))v.add(forward);if(keys.has('s'))v.sub(forward);if(keys.has('d'))v.add(right);if(keys.has('a'))v.sub(right);if(keys.has('e'))v.y+=1;if(keys.has('q'))v.y-=1;
 return v.lengthSq()?v.normalize():v;
}
// Absolute scene-units-per-second speed; target distance is intentionally absent.
export function movementStep(forward,cameraUp,keys,speed,dt){
 if(!Number.isFinite(speed)||speed<0||!Number.isFinite(dt)||dt<0)throw Error('Invalid movement step');
 return movementDirection(forward,cameraUp,keys).multiplyScalar(speed*Math.min(dt,.1));
}
// Each key ramps independently over real elapsed time; releases are immediate.
export function acceleratedStep(forward,cameraUp,pressTimes,nowMs,speed,dt,rampMs=450){
 if(!Number.isFinite(speed)||speed<0||!Number.isFinite(dt)||dt<0||!Number.isFinite(nowMs)||rampMs<=0)throw Error('Invalid movement step');
 const right=new THREE.Vector3().crossVectors(forward,cameraUp).normalize(),out=new THREE.Vector3(),worldUp=new THREE.Vector3(0,1,0);
 const axes={w:forward,s:forward.clone().negate(),d:right,a:right.clone().negate(),e:worldUp,q:worldUp.clone().negate()};
 for(const [key,start] of pressTimes){if(!axes[key]||!Number.isFinite(start))continue;const x=Math.max(0,Math.min(1,(nowMs-start)/rampMs)),weight=x*x*(3-2*x);out.addScaledVector(axes[key],weight)}
 if(out.lengthSq()>1)out.normalize();return out.multiplyScalar(speed*Math.min(dt,.1));
}
