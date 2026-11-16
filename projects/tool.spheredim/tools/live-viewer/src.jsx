import {reuseSceneData,reconcileSceneChoice} from './scene-cache.mjs';
import {copyText} from './clipboard.mjs';
import {touchGesture} from './touch-gesture.mjs';
import {serializeViewInfo,initialViewReady} from './view-info.mjs';
import {splatDescription, trajectoryFilterNotice} from './quality.mjs';
import React, {useState,useEffect,useMemo,useRef,useCallback,useLayoutEffect} from 'react';
import {createRoot} from 'react-dom/client';
import {Canvas, useThree, useFrame} from '@react-three/fiber';
import {OrbitControls, TrackballControls, Line, Bounds} from '@react-three/drei';
import * as THREE from 'three';
import {SplatMesh, SparkRenderer} from '@sparkjsdev/spark';
import {PLYLoader} from 'three/addons/loaders/PLYLoader.js';
import {LevaPanel, useControls, useCreateStore} from 'leva';
import './style.css';
import {updateTrackedCamera,finishTrackTransition,initialSceneFramer} from './camera.mjs';
import {cameraDprPolicy} from './dpr-policy.mjs';
import {arcballPoint, composeFreeLook, levelOrientation, turntablePitch} from './rotation.mjs';
import {previewAdjustment, gravityAlignment, gravityExport} from './alignment.mjs';
import {acceleratedStep} from './motion.mjs';
const noop=()=>{};

function AdaptiveCameraDpr({displayDpr}) {
  const {camera,setDpr,invalidate}=useThree();
  const settle=useRef(null);
  useEffect(()=>()=>clearTimeout(settle.current),[]);
  const policy=useMemo(()=>cameraDprPolicy(displayDpr),[displayDpr]);
  const applied=useRef(displayDpr);
  useFrame(()=>{const next=policy(camera.position.toArray(),camera.quaternion.toArray(),performance.now());if(next!==applied.current){applied.current=next;setDpr(next)}if(next!==displayDpr){clearTimeout(settle.current);settle.current=setTimeout(invalidate,210)}});
  return null;
}

function Cloud({data, pointSize}) {
  const geom=useMemo(()=>{const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(data.vertices,3));g.setAttribute('color',new THREE.Float32BufferAttribute(data.colors,3));g.computeBoundingSphere();return g},[data]);
  useEffect(()=>()=>geom.dispose(),[geom]);
  return <points geometry={geom}><pointsMaterial size={pointSize} vertexColors sizeAttenuation={false}/></points>;
}
function GaussianSplats({url,onStatus}) {
  const {gl,invalidate}=useThree();
  const spark=useMemo(()=>new SparkRenderer({renderer:gl,onDirty:invalidate}),[gl,invalidate]);
  const [mesh,setMesh]=useState(null);
  useEffect(()=>()=>spark.dispose(),[spark]);
  useEffect(()=>{let active=true;setMesh(null);onStatus('Loading Gaussian splats…');const next=new SplatMesh({url,fileName:'splat.ply'});next.initialized.then(()=>{if(active){setMesh(next);onStatus(`Loaded ${next.packedSplats?.numSplats ?? next.extSplats?.numSplats ?? 0} Gaussian splats`)}}).catch(e=>{if(active)onStatus(`Splat loading failed: ${e.message||e}`)});return()=>{active=false;next.dispose()}},[url,onStatus]);
  return <><primitive object={spark}/>{mesh&&<primitive object={mesh}/>}</>;
}
function TriangleMesh({url,onStatus}) {
  const [geometry,setGeometry]=useState(null);
  useEffect(()=>{let active=true,geo=null;const controller=new AbortController();setGeometry(null);onStatus('Loading mesh…');fetch(url,{signal:controller.signal}).then(r=>{if(!r.ok)throw Error(`HTTP ${r.status}`);return r.arrayBuffer()}).then(data=>{geo=new PLYLoader().parse(data);if(!geo.getAttribute('normal'))geo.computeVertexNormals();if(active){setGeometry(geo);onStatus('')}else geo.dispose()}).catch(e=>{if(active&&e.name!=='AbortError')onStatus(`Mesh loading failed: ${e.message||e}`)});return()=>{active=false;controller.abort();if(geo)geo.dispose()}},[url,onStatus]);
  return geometry&&<mesh geometry={geometry}><meshStandardMaterial color={geometry.getAttribute('color')?'white':'#aab6ba'} vertexColors={!!geometry.getAttribute('color')} side={THREE.DoubleSide}/></mesh>;
}
function InlineMesh({data}) {
  const geometry=useMemo(()=>{const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(data.vertices,3));if(data.colors?.length===data.vertices.length)g.setAttribute('color',new THREE.Float32BufferAttribute(data.colors,3));if(data.indices)g.setIndex(data.indices);g.computeVertexNormals();return g},[data]);
  useEffect(()=>()=>geometry.dispose(),[geometry]);
  return <mesh geometry={geometry}><meshStandardMaterial color={geometry.getAttribute('color')?'white':'#aab6ba'} vertexColors={!!geometry.getAttribute('color')} side={THREE.DoubleSide}/></mesh>;
}
function KeyboardNavigation({keys,viewMode,targetRef,speed}) {
  const {camera,controls,invalidate}=useThree();
  const forward=useMemo(()=>new THREE.Vector3(),[]);
  useFrame((_,delta)=>{const k=keys.current;if(!k.size)return;invalidate();camera.getWorldDirection(forward);const move=acceleratedStep(forward,camera.up,k,performance.now(),speed,delta);if(move.lengthSq()===0)return;const target=controls?.target??targetRef.current;camera.position.add(move);if(viewMode!=='track')target.add(move);if(controls?.target)controls.update()});
  return null;
}
function ReferenceFrame({sceneId,time,visible,onToggle,label}) {
  const video=useRef(null), target=useRef(time);
  const [size,setSize]=useState(32);
  useEffect(()=>{target.current=time;const el=video.current;if(el&&Number.isFinite(time)&&el.readyState>=1){try{el.currentTime=Math.max(0,Math.min(time,el.duration||time))}catch{}}},[time]);
  return <div className={`reference-panel${visible?' is-open':''}`} style={{width:`${size}%`,height:`${size*.85}%`}} onPointerDown={e=>e.stopPropagation()}><div className="reference-header"><div className="pip-actions" hidden={!visible}><button type="button" aria-label="Make reference frame smaller" onClick={()=>setSize(v=>Math.max(20,v-8))}>−</button><button type="button" aria-label="Make reference frame larger" onClick={()=>setSize(v=>Math.min(72,v+8))}>+</button></div><button type="button" className="reference-anchor" aria-expanded={visible} aria-controls="reference-content" onClick={onToggle}>Reference frame <span aria-hidden="true">{visible?'▴':'▾'}</span></button></div><div className="reference-content" id="reference-content" hidden={!visible}><div className="pip-label">{label}</div><video ref={video} preload="metadata" muted playsInline onLoadedMetadata={e=>{if(Number.isFinite(target.current))e.currentTarget.currentTime=Math.max(0,Math.min(target.current,e.currentTarget.duration))}} src={'/api/reference-video?scene='+encodeURIComponent(sceneId??'')}/><div className="pip-resize">Drag lower-right corner to resize</div></div></div>;
}
function QuaternionOrbit({targetRef}) {
  const {camera,gl}=useThree();
  useEffect(()=>{const el=gl.domElement;let previous=null,pan=false;
    const down=e=>{if(e.button!==0&&e.button!==1&&e.button!==2)return;e.preventDefault();previous={x:e.clientX,y:e.clientY};pan=e.button!==0||e.shiftKey;el.setPointerCapture(e.pointerId)};
    const move=e=>{if(!previous)return;const rect=el.getBoundingClientRect();if(pan){const dx=(e.clientX-previous.x)/Math.max(rect.width,1),dy=(e.clientY-previous.y)/Math.max(rect.height,1),d=Math.max(camera.position.distanceTo(targetRef.current),.1),right=new THREE.Vector3(1,0,0).applyQuaternion(camera.quaternion),up=new THREE.Vector3(0,1,0).applyQuaternion(camera.quaternion),offset=right.multiplyScalar(-dx*d*2).addScaledVector(up,dy*d*2);camera.position.add(offset);targetRef.current.add(offset)}else{const old=camera.quaternion.clone(),next=composeFreeLook(old,arcballPoint(previous.x,previous.y,rect),arcballPoint(e.clientX,e.clientY,rect)),world=next.clone().multiply(old.clone().invert());camera.position.sub(targetRef.current).applyQuaternion(world).add(targetRef.current);camera.quaternion.copy(next)}camera.updateMatrixWorld();previous={x:e.clientX,y:e.clientY}};
    const end=()=>{previous=null},noMenu=e=>e.preventDefault(),wheel=e=>{e.preventDefault();const offset=camera.position.clone().sub(targetRef.current).multiplyScalar(Math.exp(Math.max(-2,Math.min(2,e.deltaY*.001))));if(offset.lengthSq()>1e-8)camera.position.copy(targetRef.current).add(offset)};
    el.addEventListener('pointerdown',down);el.addEventListener('pointermove',move);el.addEventListener('pointerup',end);el.addEventListener('pointercancel',end);el.addEventListener('contextmenu',noMenu);el.addEventListener('wheel',wheel,{passive:false});return()=>{el.removeEventListener('pointerdown',down);el.removeEventListener('pointermove',move);el.removeEventListener('pointerup',end);el.removeEventListener('pointercancel',end);el.removeEventListener('contextmenu',noMenu);el.removeEventListener('wheel',wheel)};
  },[camera,gl,targetRef]);return null;
}
function PivotMarker({targetRef}) {
  const marker=useRef(null);
  useFrame(()=>{if(marker.current)marker.current.position.copy(targetRef.current)});
  return <points ref={marker} renderOrder={10}><bufferGeometry><float32BufferAttribute attach="attributes-position" args={[[0,0,0],3]}/></bufferGeometry><pointsMaterial size={7} sizeAttenuation={false} depthTest={false} color="#f4a8df"/></points>;
}
function RotationTransition({rotationMode,targetRef}) {
  const {camera,get,invalidate}=useThree(),previous=useRef(rotationMode);
  useLayoutEffect(()=>{const before=previous.current;previous.current=rotationMode;if(before===rotationMode||rotationMode!=='turntable')return;
    const distance=Math.max(camera.position.distanceTo(targetRef.current),.05),forward=new THREE.Vector3(0,0,-1).applyQuaternion(camera.quaternion).normalize();
    camera.quaternion.copy(levelOrientation(camera.quaternion));camera.up.set(0,1,0);targetRef.current.copy(camera.position).addScaledVector(forward,distance);camera.updateMatrixWorld();
    const controls=get().controls;if(controls?.target){controls.target.copy(targetRef.current);controls.update()}invalidate();
  },[rotationMode,camera,get,targetRef,invalidate]);return null;
}
function SceneControls({rotationMode,targetRef}) {
  const controls=useRef(null),{camera}=useThree();
  const saveTarget=()=>{if(controls.current?.target)targetRef.current.copy(controls.current.target)};
  useEffect(()=>{if(rotationMode==='turntable')camera.up.set(0,1,0)},[camera,rotationMode]);
  return rotationMode==='free'?<QuaternionOrbit targetRef={targetRef}/>:<OrbitControls ref={controls} makeDefault enableDamping={false} target={targetRef.current} onChange={saveTarget}/>;
}
function OrbitDistance({distance,targetRef}) {
  const {camera,get,invalidate}=useThree(),previous=useRef(distance);
  useEffect(()=>{if(previous.current===distance)return;previous.current=distance;const forward=new THREE.Vector3();camera.getWorldDirection(forward);targetRef.current.copy(camera.position).addScaledVector(forward,distance);const controls=get().controls;if(controls?.target){controls.target.copy(targetRef.current);controls.update()}camera.updateMatrixWorld();invalidate()},[camera,get,distance,targetRef,invalidate]);return null;
}
function TrackCamera({pose,up,pivotDistance,rotationMode,targetRef,onDisengage,correction,invertLook,savedCamera,selectedIndex}) {
  const {camera,gl,get,invalidate}=useThree();
  const poseKey=pose?.matrix?.flat().join(','),upKey=up?.join(','),correctionKey=correction.toArray().join(','),previousAlignment=useRef(null);
  const distance=useRef(pivotDistance);distance.current=pivotDistance;
  const updateTarget=()=>{const f=new THREE.Vector3();camera.getWorldDirection(f);targetRef.current.copy(camera.position).addScaledVector(f,distance.current)};
  useEffect(()=>{if(!pose){previousAlignment.current=null;return}const prior=previousAlignment.current,first=!prior;previousAlignment.current=updateTrackedCamera(camera,pose.matrix,up,correction,previousAlignment.current);if(first&&savedCamera?.mode==='track'&&savedCamera.index===selectedIndex&&!savedCamera.used){camera.quaternion.fromArray(savedCamera.quaternion).normalize();savedCamera.used=true}finishTrackTransition(camera,rotationMode,prior,previousAlignment.current);camera.updateMatrixWorld();updateTarget();invalidate()},[camera,poseKey,upKey,correctionKey,rotationMode,invalidate]);
  useEffect(()=>{updateTarget()},[camera,pivotDistance]);
  useEffect(()=>{const el=gl.domElement;let previous=null;
    const down=e=>{if(e.button===1||e.button===2||(e.button===0&&e.shiftKey)){e.preventDefault();let prior={x:e.clientX,y:e.clientY};onDisengage();const pan=ev=>{const rect=el.getBoundingClientRect(),dx=(ev.clientX-prior.x)/Math.max(1,rect.width),dy=(ev.clientY-prior.y)/Math.max(1,rect.height);const right=new THREE.Vector3(1,0,0).applyQuaternion(camera.quaternion),upAxis=new THREE.Vector3(0,1,0).applyQuaternion(camera.quaternion);const offset=right.multiplyScalar(-dx*distance.current*2).addScaledVector(upAxis,dy*distance.current*2);camera.position.add(offset);targetRef.current.add(offset);const controls=get().controls;if(controls?.target){controls.target.copy(targetRef.current);controls.update()}prior={x:ev.clientX,y:ev.clientY}};const stop=()=>{window.removeEventListener('pointermove',pan);window.removeEventListener('pointerup',stop);window.removeEventListener('blur',stop)};window.addEventListener('pointermove',pan);window.addEventListener('pointerup',stop);window.addEventListener('blur',stop);return}if(e.button!==0)return;previous={x:e.clientX,y:e.clientY};el.setPointerCapture(e.pointerId)};
    const move=e=>{if(!previous)return;const rect=el.getBoundingClientRect(),dx=(e.clientX-previous.x)/Math.max(rect.width,1),dy=(e.clientY-previous.y)/Math.max(rect.height,1);
      if(rotationMode==='turntable'){const yaw=new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0,1,0),(invertLook?1:-1)*dx*Math.PI*2);camera.quaternion.premultiply(yaw);camera.quaternion.copy(turntablePitch(camera.quaternion,(invertLook?1:-1)*dy*Math.PI))}
      else {const a=arcballPoint(previous.x,previous.y,rect),b=arcballPoint(e.clientX,e.clientY,rect);camera.quaternion.copy(composeFreeLook(camera.quaternion,invertLook?b:a,invertLook?a:b))}
      camera.updateMatrixWorld();updateTarget();previous={x:e.clientX,y:e.clientY}};
    const end=()=>{previous=null};const noMenu=e=>e.preventDefault();el.addEventListener('contextmenu',noMenu);el.addEventListener('pointerdown',down);el.addEventListener('pointermove',move);el.addEventListener('pointerup',end);el.addEventListener('pointercancel',end);
    return()=>{el.removeEventListener('contextmenu',noMenu);el.removeEventListener('pointerdown',down);el.removeEventListener('pointermove',move);el.removeEventListener('pointerup',end);el.removeEventListener('pointercancel',end)};
  },[camera,gl,rotationMode,onDisengage,invertLook]);
  return null;
}
function CameraSession({saved,initialView,viewMode,selectedIndex,targetRef,ready,rotationMode,centerMode,keys}) {
  const {camera,controls,invalidate}=useThree(),restored=useRef(false),pending=useRef(null),latest=useRef(null);
  useEffect(()=>()=>{clearTimeout(pending.current);if(latest.current)try{sessionStorage.setItem('spheredim.camera',latest.current)}catch{}},[]);
  useEffect(()=>{if(restored.current||!ready)return;if(initialView){if(!initialViewReady(initialView,viewMode,rotationMode,centerMode,selectedIndex))return;const c=initialView.camera;if(viewMode!=='track')camera.position.fromArray(c.position);camera.quaternion.fromArray(c.quaternion_xyzw);camera.up.fromArray(c.up);camera.fov=c.fov_degrees;camera.near=c.near;camera.far=c.far;camera.updateProjectionMatrix();targetRef.current.fromArray(initialView.controls.target);camera.updateMatrixWorld();if(controls?.target)controls.target.copy(targetRef.current);restored.current=true;invalidate();return}if(saved?.mode==='orbit'&&viewMode==='orbit'&&!saved.used){if(centerMode==='pivot'&&rotationMode==='turntable'&&!controls)return;camera.position.fromArray(saved.position);camera.quaternion.fromArray(saved.quaternion).normalize();targetRef.current.fromArray(saved.target);camera.updateMatrixWorld();if(controls?.target){controls.target.copy(targetRef.current);controls.update()}saved.used=true;invalidate()}restored.current=true},[camera,controls,ready,saved,initialView,viewMode,selectedIndex,rotationMode,centerMode,targetRef,invalidate]);
  useFrame(()=>{if(!ready||!restored.current)return;const next=JSON.stringify({mode:viewMode,index:selectedIndex,position:camera.position.toArray(),quaternion:camera.quaternion.toArray(),target:targetRef.current.toArray()});if(next===latest.current)return;latest.current=next;clearTimeout(pending.current);pending.current=setTimeout(()=>{try{sessionStorage.setItem('spheredim.camera',latest.current)}catch{}},300)});return null;
}
function readCamera(){try{const s=JSON.parse(sessionStorage.getItem('spheredim.camera'));return s&&['orbit','track'].includes(s.mode)&&[s.position,s.quaternion,s.target].every((v,i)=>Array.isArray(v)&&v.length===(i===1?4:3)&&v.every(Number.isFinite))?s:null}catch{return null}}
function readChoice(key,values,fallback){try{const v=sessionStorage.getItem(key);return values.includes(v)?v:fallback}catch{return fallback}}
function readNumber(key,fallback,min,max){try{const raw=sessionStorage.getItem(key),v=Number(raw);return raw!==null&&Number.isFinite(v)&&v>=min&&v<=max?v:fallback}catch{return fallback}}
function readFlag(key){try{return sessionStorage.getItem(key)==='true'}catch{return false}}
function FitScene({points,trajectory,alignment,targetRef,enabled,viewMode}) {
  const {camera,get,invalidate}=useThree(),frame=useMemo(()=>initialSceneFramer(),[]);
  useEffect(()=>{if(!enabled||viewMode!=='orbit')return;const fit=frame(points?.vertices,trajectory,alignment);if(!fit)return;
    const {center,size}=fit,distance=Math.max(size.length()*.65,.05);targetRef.current.copy(center);camera.position.copy(center).add(new THREE.Vector3(distance*.65,distance*.45,distance*.65));camera.lookAt(center);camera.updateMatrixWorld();const controls=get().controls;if(controls?.target){controls.target.copy(center);controls.update()}invalidate();
  },[points,trajectory,alignment,targetRef,enabled,viewMode,camera,get,frame,invalidate]);return null;
}
function RenderDebug() {
  const count=useRef(0),element=useRef(null);
  useEffect(()=>{if(new URLSearchParams(location.search).get('renderDebug')!=='1')return;const el=document.createElement('output');el.setAttribute('aria-label','Render frames');el.style.cssText='position:fixed;bottom:0;left:0;z-index:9999;background:#000;color:#fff;padding:4px';document.body.appendChild(el);element.current=el;return()=>{element.current=null;el.remove()}},[]);
  useFrame(()=>{if(element.current)element.current.textContent=`Render frames: ${++count.current}`});return null;
}
function DemandInteraction() {
  const {gl,invalidate}=useThree();
  useEffect(()=>{const canvas=gl.domElement;const pointer=e=>{if(e.buttons)invalidate()};const refresh=()=>invalidate();window.addEventListener('pointermove',pointer);window.addEventListener('pointerdown',refresh);window.addEventListener('pointerup',refresh);window.addEventListener('keydown',refresh);window.addEventListener('keyup',refresh);canvas.addEventListener('wheel',refresh,{passive:true});return()=>{window.removeEventListener('pointermove',pointer);window.removeEventListener('pointerdown',refresh);window.removeEventListener('pointerup',refresh);window.removeEventListener('keydown',refresh);window.removeEventListener('keyup',refresh);canvas.removeEventListener('wheel',refresh)}} ,[gl,invalidate]);return null;
}
// Screen-sized discs keep the track legible without world-sized geometry.
function TrackMarkers({positions,selected=false}) {
  const {viewport}=useThree();
  const uniforms=useMemo(()=>({size:{value:(selected?18:7)*viewport.dpr},selected:{value:selected?1:0}}),[selected,viewport.dpr]);
  return <points renderOrder={selected?101:100} frustumCulled={false}><bufferGeometry><float32BufferAttribute attach="attributes-position" args={[positions,3]}/></bufferGeometry><shaderMaterial uniforms={uniforms} transparent depthTest={false} depthWrite={false} vertexShader={`uniform float size; void main(){gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);gl_PointSize=size;}`} fragmentShader={`uniform float selected; void main(){float r=length(gl_PointCoord-vec2(0.5))*2.0;if(r>1.0)discard;vec3 c;if(selected>0.5){c=r>0.88?vec3(0.03,0.07,0.09):r>0.53?vec3(1.0,0.72,0.17):r>0.30?vec3(0.05,0.09,0.1):vec3(1.0);}else{c=r>0.68?vec3(0.03,0.07,0.09):vec3(0.55,1.0,0.91);}gl_FragColor=vec4(c,1.0);}`}/></points>;
}
function TouchNavigation({viewMode,rotationMode,centerMode,targetRef,onDisengage,pivotDistance}) {
  const {camera,gl,get,invalidate}=useThree(),settings=useRef(null);
  settings.current={viewMode,rotationMode,centerMode,onDisengage,pivotDistance};
  useEffect(()=>{const el=gl.domElement,gesture=touchGesture();
    const capture=e=>{if(e.pointerType!=='touch')return false;e.preventDefault();e.stopImmediatePropagation();return true};
    const down=e=>{if(!capture(e))return;try{el.setPointerCapture(e.pointerId)}catch{}const count=gesture.down(e.pointerId,e.clientX,e.clientY);if(count===2&&settings.current.viewMode==='track')settings.current.onDisengage()};
    const move=e=>{if(!capture(e))return;const g=gesture.move(e.pointerId,e.clientX,e.clientY);if(!g)return;const rect=el.getBoundingClientRect(),dx=(g.to.x-g.from.x)/Math.max(1,rect.width),dy=(g.to.y-g.from.y)/Math.max(1,rect.height),opt=settings.current;
      if(g.count>=2){const d=opt.centerMode==='pivot'&&opt.viewMode==='orbit'?Math.max(camera.position.distanceTo(targetRef.current),.1):opt.pivotDistance;const right=new THREE.Vector3(1,0,0).applyQuaternion(camera.quaternion),up=new THREE.Vector3(0,1,0).applyQuaternion(camera.quaternion),offset=right.multiplyScalar(-dx*d*2).addScaledVector(up,dy*d*2);camera.position.add(offset);targetRef.current.add(offset);
        if(g.count===2&&Number.isFinite(g.scale)&&g.scale>0){const scale=Math.max(.8,Math.min(1.25,1/g.scale));if(opt.centerMode==='pivot'&&opt.viewMode==='orbit'){const radius=camera.position.clone().sub(targetRef.current);if(radius.lengthSq()>1e-8)camera.position.copy(targetRef.current).add(radius.multiplyScalar(scale))}else{const forward=new THREE.Vector3();camera.getWorldDirection(forward);const step=d*(1-scale);camera.position.addScaledVector(forward,step);targetRef.current.addScaledVector(forward,step)}}
        const controls=get().controls;if(controls?.target){controls.target.copy(targetRef.current);controls.update()}}
      else if(g.count===1){const old=camera.quaternion.clone();let next;if(opt.rotationMode==='turntable'){const sign=opt.viewMode==='track'?1:-1;next=old.clone().premultiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0,1,0),sign*dx*Math.PI*2));next=turntablePitch(next,sign*dy*Math.PI)}else{const a=arcballPoint(g.from.x,g.from.y,rect),b=arcballPoint(g.to.x,g.to.y,rect);next=composeFreeLook(old,opt.viewMode==='track'?b:a,opt.viewMode==='track'?a:b)}if(opt.viewMode==='orbit'&&opt.centerMode==='pivot'){const world=next.clone().multiply(old.clone().invert());camera.position.sub(targetRef.current).applyQuaternion(world).add(targetRef.current)}camera.quaternion.copy(next)}
      camera.updateMatrixWorld();invalidate()};
    const end=e=>{if(!capture(e))return;gesture.up(e.pointerId);try{if(el.hasPointerCapture(e.pointerId))el.releasePointerCapture(e.pointerId)}catch{}};
    // Safari can still claim scrolling independently of pointer events. Only
    // cancel touches that started on this canvas, never overlay controls.
    const viewport=el.closest('.viewport'),owned=new Set();
    const touchStart=e=>{for(const t of e.changedTouches)if(t.target===el)owned.add(t.identifier);if([...e.changedTouches].some(t=>owned.has(t.identifier))&&e.cancelable)e.preventDefault()};
    const touchMove=e=>{if([...e.changedTouches].some(t=>owned.has(t.identifier))&&e.cancelable)e.preventDefault()};
    const touchEnd=e=>{for(const t of e.changedTouches)owned.delete(t.identifier)};
    viewport?.addEventListener('touchstart',touchStart,{capture:true,passive:false});viewport?.addEventListener('touchmove',touchMove,{capture:true,passive:false});viewport?.addEventListener('touchend',touchEnd,true);viewport?.addEventListener('touchcancel',touchEnd,true);
    for(const [name,fn] of [['pointerdown',down],['pointermove',move],['pointerup',end],['pointercancel',end]])el.addEventListener(name,fn,{capture:true,passive:false});
    return()=>{viewport?.removeEventListener('touchstart',touchStart,true);viewport?.removeEventListener('touchmove',touchMove,true);viewport?.removeEventListener('touchend',touchEnd,true);viewport?.removeEventListener('touchcancel',touchEnd,true);owned.clear();for(const id of gesture.ids())try{if(el.hasPointerCapture(id))el.releasePointerCapture(id)}catch{}gesture.clear();for(const [name,fn] of [['pointerdown',down],['pointermove',move],['pointerup',end],['pointercancel',end]])el.removeEventListener(name,fn,true)};
  },[camera,gl,get,invalidate,targetRef]);return null;
}
function ViewInfoBridge({captureRef,targetRef}) {
  const {camera,gl}=useThree();
  useEffect(()=>{captureRef.current=()=>{camera.updateMatrixWorld();const position=new THREE.Vector3(),quaternion=new THREE.Quaternion();camera.getWorldPosition(position);camera.getWorldQuaternion(quaternion);const rect=gl.domElement.getBoundingClientRect();return {camera:{position:position.toArray(),quaternion_xyzw:quaternion.toArray(),up:camera.up.toArray(),fov_degrees:camera.fov,aspect:camera.aspect,near:camera.near,far:camera.far},target:targetRef.current.toArray(),viewport:{width_css_px:rect.width,height_css_px:rect.height,dpr:gl.getPixelRatio()}}};return()=>{captureRef.current=null}},[camera,gl,captureRef,targetRef]);return null;
}
function Scene({captureRef,state,pointSize,representation,showRaw,onStatus,keys,viewMode,selectedPose,pivotDistance,rotationMode,centerMode,onDisengage,pitch,roll,savedCamera,selectedIndex,movementSpeed,fitScene}) {
  const targetRef=useRef(new THREE.Vector3());
  const trajectory=showRaw&&Array.isArray(state.rawTrajectory)?state.rawTrajectory:state.trajectory;
  const path=useMemo(()=>{const p=[];for(let i=0;i<trajectory.length;i+=3)p.push(trajectory.slice(i,i+3));return p},[trajectory]);
  const correction=useMemo(()=>previewAdjustment(pitch,roll),[pitch,roll]);
  const quat=useMemo(()=>gravityAlignment(state.up,pitch,roll),[state.up,pitch,roll]);
  const focus=useMemo(()=>{if(!path.length)return null;const core=path.slice(0,Math.max(1,Math.ceil(path.length*.9)));const box=new THREE.Box3();core.forEach(p=>box.expandByPoint(new THREE.Vector3(...p).applyQuaternion(quat)));const center=box.getCenter(new THREE.Vector3()),size=box.getSize(new THREE.Vector3());size.set(Math.max(size.x,1),Math.max(size.y,1),Math.max(size.z,1));return {center,size}},[path,quat]);
  const last=selectedPose?selectedPose.matrix.map(row=>row[3]):path.at(-1);
  const worldFromTrain=useMemo(()=>{const a=state.worldFromTrain?.flat?.();return Array.isArray(a)&&a.length===16&&a.every(Number.isFinite)?new THREE.Matrix4().set(...a):new THREE.Matrix4()},[state.worldFromTrain]);
  const splatUrl=`/api/splat.ply?scene=${encodeURIComponent(state.sceneId??'')}&v=${encodeURIComponent(state.splatVersion??'latest')}`;
  const meshUrl=`/api/mesh.ply?scene=${encodeURIComponent(state.sceneId??'')}&v=${encodeURIComponent(state.meshVersion??'latest')}`;
  const centers=!state.splatAvailable&&state.splatPoints;
  return <><ViewInfoBridge captureRef={captureRef} targetRef={targetRef}/><TouchNavigation viewMode={viewMode} rotationMode={rotationMode} centerMode={centerMode} targetRef={targetRef} onDisengage={onDisengage} pivotDistance={pivotDistance}/><color attach="background" args={['#101820']}/><ambientLight intensity={1}/><gridHelper args={[10,20,'#4a6576','#273a46']}/><axesHelper args={[1]}/>
    {focus&&!savedCamera&&!fitScene&&<Bounds fit clip maxDuration={0} margin={1.5}><mesh position={focus.center}><boxGeometry args={focus.size.toArray()}/><meshBasicMaterial visible={false}/></mesh></Bounds>}
    <group quaternion={quat}>{representation==='sparse'&&state.points?.shownCount>0&&<Cloud data={state.points} pointSize={pointSize}/>}{representation==='dense'&&state.denseSpace!=='train'&&state.densePoints?.shownCount>0&&<Cloud data={state.densePoints} pointSize={pointSize}/>}
      <group matrix={worldFromTrain} matrixAutoUpdate={false}>{representation==='dense'&&state.denseSpace==='train'&&state.densePoints?.shownCount>0&&<Cloud data={state.densePoints} pointSize={pointSize}/>}{representation==='splat'&&state.splatAvailable&&<GaussianSplats url={splatUrl} onStatus={onStatus}/>}{representation==='splat'&&centers?.shownCount>0&&<Cloud data={centers} pointSize={pointSize}/>}{representation==='mesh'&&state.meshAvailable&&<TriangleMesh url={meshUrl} onStatus={onStatus}/>} {representation==='mesh'&&!state.meshAvailable&&state.mesh&&<InlineMesh data={state.mesh}/>}</group>
      {path.length>1&&<><Line points={path} color="#42d7c4" lineWidth={2}/><TrackMarkers positions={trajectory}/></>}{last&&<TrackMarkers positions={last} selected/>}</group>{centerMode==='pivot'&&viewMode==='orbit'&&<PivotMarker targetRef={targetRef}/>}<RotationTransition rotationMode={rotationMode} targetRef={targetRef}/>{viewMode==='orbit'&&centerMode==='pivot'?<><SceneControls rotationMode={rotationMode} targetRef={targetRef}/><KeyboardNavigation keys={keys} viewMode={viewMode} targetRef={targetRef} speed={movementSpeed}/><OrbitDistance distance={pivotDistance} targetRef={targetRef}/></>:<><TrackCamera pose={viewMode==='track'?selectedPose:null} up={state.up} pivotDistance={pivotDistance} rotationMode={rotationMode} targetRef={targetRef} onDisengage={viewMode==='track'?onDisengage:noop} correction={correction} invertLook={viewMode==='track'} savedCamera={state.initialView?null:savedCamera} selectedIndex={selectedIndex}/>{viewMode==='orbit'&&<KeyboardNavigation keys={keys} viewMode={viewMode} targetRef={targetRef} speed={movementSpeed}/>}</>}<FitScene points={state.points} trajectory={state.trajectory} alignment={quat} targetRef={targetRef} enabled={fitScene&&!state.initialView} viewMode={viewMode}/><CameraSession initialView={state.initialView} saved={fitScene?null:savedCamera} viewMode={viewMode} selectedIndex={selectedIndex} targetRef={targetRef} ready={state.trajectory.length>0} rotationMode={rotationMode} centerMode={centerMode} keys={keys}/></>;
}
function duration(seconds){if(!Number.isFinite(seconds)||seconds<0)return '—';return `${Math.floor(seconds/60)}m ${Math.floor(seconds%60)}s`}
function Bar({value,total,label}) {const known=Number.isFinite(value)&&Number.isFinite(total)&&total>0;const percent=known?Math.max(0,Math.min(100,100*value/total)):0;return <div className="bar" role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} {...(known?{'aria-valuenow':Math.round(percent)}:{})}><div style={{width:percent+'%'}}/></div>}
function LogTail({logs,details,stages,open,onClose,splatRun,splatCheckpoint,denseLabel,referenceLabel}) {
  const [source,setSource]=useState(0);
  const activeLines=logs[source]?.lines||[];
  const container=useRef(null),follow=useRef(true);
  useEffect(()=>{const el=container.current;if(el&&open&&follow.current)el.scrollTop=el.scrollHeight},[activeLines,open]);
  const onScroll=()=>{const el=container.current;follow.current=el.scrollHeight-el.scrollTop-el.clientHeight<24};
  return <section className="log-drawer" hidden={!open} aria-label="Activity log"><div className="drawer-header"><div><h2>Activity</h2><p>Latest output · updates every 2 seconds</p></div>{logs.length>0&&<label className="log-source"><span>Source</span><select value={source} onChange={e=>{follow.current=true;setSource(Number(e.target.value))}}>{logs.map((log,i)=><option key={i} value={i}>{log.name}</option>)}</select></label>}<button type="button" onClick={onClose} aria-label="Close activity log">×</button></div><div className="activity-stages">{stages.map((stage,i)=><section className="sfm-strip" key={i}><div><strong>{stage.name}</strong><span>{[stage.detail,stage.status].filter(Boolean).join(' · ')}</span></div><div className="sfm-metrics">{Number.isFinite(stage.current)&&stage.total>0&&<span>{stage.current.toLocaleString()} / {stage.total.toLocaleString()}</span>}{(stage.metrics||[]).map((metric,j)=><span key={j}>{metric.label}: {metric.value}</span>)}{stage.error&&<span>{stage.error}</span>}</div></section>)}</div><details><summary>Reconstruction details</summary>{splatDescription(splatRun,splatCheckpoint)&&<p>{splatDescription(splatRun,splatCheckpoint)}</p>}{denseLabel&&<p>{denseLabel}</p>}{referenceLabel&&<p>Reference: {referenceLabel}</p>}{details.map((detail,i)=><p key={i}>{detail}</p>)}</details><pre ref={container} onScroll={onScroll} tabIndex={0} aria-label="Recent pipeline log">{activeLines.length?activeLines.join('\n'):'Waiting for log output…'}</pre></section>;
}
function initialPointSize(){try {const saved=sessionStorage.getItem('spheredim.pointSize');if(saved!==null){const n=Number(saved);if(Number.isFinite(n)&&n>=.5&&n<=10)return n}}catch{}return 2}
function SceneAdjustments({pointSize,setPointSize,movementSpeed,setMovementSpeed,viewMode,showPointSize}) {
  const store=useCreateStore();
  const [,set]=useControls(()=>({
    'Point size':{value:pointSize,min:.5,max:10,step:.5,onChange:v=>setPointSize(v),render:()=>showPointSize},
    'Speed (units/s)':{value:movementSpeed,min:.1,max:10,step:.1,onChange:v=>setMovementSpeed(v)}
  }),{store},[viewMode,showPointSize]);
  useEffect(()=>set({'Point size':pointSize,'Speed (units/s)':movementSpeed}),[set,pointSize,movementSpeed]);
  const theme=useMemo(()=>({colors:{elevation1:'#151d22',elevation2:'#202b30',elevation3:'#344642',accent1:'#336b5b',accent2:'#60c3a5',accent3:'#a0e6cd',highlight1:'#8fa7a0',highlight2:'#becfca',highlight3:'#edf5f1'},fontSizes:{root:'12px'},sizes:{rootWidth:'100%',controlWidth:'57%'}}),[]);
  return <div className="leva-controls"><LevaPanel store={store} fill flat titleBar={false} hideCopyButton theme={theme}/></div>;
}
function AlignmentControls({pitch,setPitch,roll,setRoll,up}) {
  const store=useCreateStore(),[copyState,setCopyState]=useState('');
  const [,set]=useControls(()=>({Pitch:{value:pitch,min:-90,max:90,step:.5,onChange:v=>setPitch(v)},Roll:{value:roll,min:-90,max:90,step:.5,onChange:v=>setRoll(v)}}),{store});
  useEffect(()=>set({Pitch:pitch,Roll:roll}),[set,pitch,roll]);
  const theme=useMemo(()=>({colors:{elevation1:'#151d22',elevation2:'#202b30',elevation3:'#344642',accent1:'#336b5b',accent2:'#60c3a5',accent3:'#a0e6cd',highlight1:'#8fa7a0',highlight2:'#becfca',highlight3:'#edf5f1'},fontSizes:{root:'12px'},sizes:{rootWidth:'100%',controlWidth:'57%'}}),[]);
  const copy=async()=>{try{await navigator.clipboard.writeText(JSON.stringify(gravityExport(up,pitch,roll),null,2));setCopyState('Copied gravity JSON')}catch{setCopyState('Copy unavailable in this browser')}};
  return <><div className="leva-controls"><LevaPanel store={store} fill flat titleBar={false} hideCopyButton theme={theme}/></div><div className="preset-row"><button type="button" onClick={()=>{setPitch(0);setRoll(0)}}>Reset to IMU</button><button type="button" onClick={copy}>Copy gravity JSON</button></div><p className="help-text" aria-live="polite">{copyState||'Preview only. Copied world-up can be used by the Blender alignment helper.'}</p></>;
}
function savedAngle(key){try{const n=Number(sessionStorage.getItem(key));return Number.isFinite(n)&&Math.abs(n)<=90?n:0}catch{return 0}}
function App(){
  const [state,setState]=useState({progress:null,trajectory:[],points:null});
  const [sceneChoice,setSceneChoice]=useState('');
  const [displayDpr]=useState(()=>Math.max(1,Math.min(2,window.devicePixelRatio||1)));
  const [savedCamera]=useState(readCamera);
  const captureRef=useRef(null),copyTimer=useRef(null),[copyStatus,setCopyStatus]=useState(''),[manualCopy,setManualCopy]=useState('');
  useEffect(()=>()=>clearTimeout(copyTimer.current),[]);
  const [connected,setConnected]=useState(false),[pointSize,setPointSize]=useState(initialPointSize),[representation,setRepresentation]=useState(()=>readChoice('spheredim.representation',['sparse','dense','splat','mesh'],'sparse')),[showRaw,setShowRaw]=useState(()=>readFlag('spheredim.showRaw')),[assetStatus,setAssetStatus]=useState(''),[viewMode,setViewMode]=useState(()=>readChoice('spheredim.viewMode',['orbit','track'],'orbit')),[trackIndex,setTrackIndex]=useState(()=>readNumber('spheredim.trackIndex',0,0,1e7)),[showOriginal,setShowOriginal]=useState(()=>readFlag('spheredim.showOriginal')),[pivotDistance,setPivotDistance]=useState(()=>readNumber('spheredim.viewDistance',1,.05,20)),[settingsOpen,setSettingsOpen]=useState(()=>readFlag('spheredim.settingsOpen')),[logOpen,setLogOpen]=useState(()=>readFlag('spheredim.logOpen')),[rotationMode,setRotationMode]=useState(()=>readChoice('spheredim.rotationMode',['free','turntable'],'turntable')),[centerMode,setCenterMode]=useState(()=>readChoice('spheredim.centerMode',['point','pivot'],'pivot')),[movementSpeed,setMovementSpeed]=useState(()=>readNumber('spheredim.movementSpeed',1,.1,10)),[leftTrack,setLeftTrack]=useState(false),[pitch,setPitch]=useState(()=>savedAngle('spheredim.pitch')),[roll,setRoll]=useState(()=>savedAngle('spheredim.roll'));
  const reportAssetStatus=useCallback(value=>setAssetStatus(value),[]);
  const initialViewScene=useRef(null);useEffect(()=>{const v=state.initialView;if(!state.sceneId||initialViewScene.current===state.sceneId)return;initialViewScene.current=state.sceneId;if(!v)return;setViewMode(v.controls.mode);setRotationMode(v.controls.rotation);setCenterMode(v.controls.view);setPivotDistance(v.controls.pivot_distance);setRepresentation(v.representation);if(Number.isInteger(v.track?.index)&&v.track.index>=0)setTrackIndex(v.track.index);if(Number.isFinite(v.alignment?.correction_pitch_degrees))setPitch(v.alignment.correction_pitch_degrees);if(Number.isFinite(v.alignment?.correction_roll_degrees))setRoll(v.alignment.correction_roll_degrees)},[state.sceneId,state.initialView]);
  useEffect(()=>{if(viewMode==='track'&&centerMode!=='point')setCenterMode('point')},[viewMode,centerMode]);
  const disengageTrack=useCallback(()=>{setLeftTrack(true);setViewMode('orbit')},[]);
  useEffect(()=>{const dismiss=e=>{if(e.key==='Escape'){setSettingsOpen(false);setLogOpen(false)}};window.addEventListener('keydown',dismiss);return()=>window.removeEventListener('keydown',dismiss)},[]);
  const keys=useRef(new Map());
  useEffect(()=>{const clear=()=>keys.current.clear();const visibility=()=>{if(document.hidden)clear()};window.addEventListener('blur',clear);document.addEventListener('visibilitychange',visibility);return()=>{window.removeEventListener('blur',clear);document.removeEventListener('visibilitychange',visibility)}},[]);
  const keyDown=e=>{if(e.target!==e.currentTarget||e.altKey||e.ctrlKey||e.metaKey)return;const k=e.key.toLowerCase();if(k==='1'){e.preventDefault();keys.current.clear();setPivotDistance(.1);setCenterMode('point')}else if(k==='2'){e.preventDefault();keys.current.clear();setPivotDistance(1);setCenterMode('pivot');setViewMode('orbit')}else if(['w','a','s','d','q','e'].includes(k)){e.preventDefault();if(!keys.current.has(k))keys.current.set(k,performance.now());if(viewMode==='track')disengageTrack()}};
  const keyUp=e=>{const k=e.key.toLowerCase();if(e.target===e.currentTarget&&['w','a','s','d','q','e'].includes(k)){e.preventDefault();keys.current.delete(k)}};
  useEffect(()=>{try{sessionStorage.setItem('spheredim.pointSize',String(pointSize));sessionStorage.setItem('spheredim.pitch',String(pitch));sessionStorage.setItem('spheredim.roll',String(roll));for(const [k,v] of Object.entries({representation,showRaw,viewMode,trackIndex,showOriginal,viewDistance:pivotDistance,settingsOpen,logOpen,rotationMode,centerMode,movementSpeed}))sessionStorage.setItem('spheredim.'+k,String(v))}catch{}},[pointSize,pitch,roll,representation,showRaw,viewMode,trackIndex,showOriginal,pivotDistance,settingsOpen,logOpen,rotationMode,centerMode,movementSpeed]);
  useEffect(()=>{let stopped=false,lastText=null;async function refresh(){try{let r=await fetch('/api/state?scene='+encodeURIComponent(sceneChoice),{cache:'no-store'});if(!r.ok)throw Error();let text=await r.text();if(sceneChoice&&JSON.parse(text).configError==='Unknown scene'){r=await fetch('/api/state',{cache:'no-store'});if(!r.ok)throw Error();text=await r.text()}if(!stopped){if(text!==lastText){const next=JSON.parse(text);lastText=text;setSceneChoice(choice=>reconcileSceneChoice(choice,next));setState(previous=>reuseSceneData(previous,next))}setConnected(true)}}catch{if(!stopped)setConnected(false)}}refresh();let id=setInterval(refresh,2000);return()=>{stopped=true;clearInterval(id)}},[sceneChoice]);
  const lastScene=useRef(null);useEffect(()=>{if(state.sceneId!==lastScene.current){lastScene.current=state.sceneId;if(state.sceneId&&((representation==='splat'&&!state.splatAvailable&&!state.splatPoints)||(representation==='mesh'&&!state.meshAvailable&&!state.mesh)||(representation==='dense'&&!state.densePoints)))setRepresentation('sparse')}},[state.sceneId,representation,state.splatAvailable,state.splatPoints,state.meshAvailable,state.mesh,state.densePoints]);
  const stages=Array.isArray(state.stages)?state.stages:[], pipeline=state.currentActivity===null||state.currentActivity===undefined?null:stages[state.currentActivity], logs=Array.isArray(state.logs)?state.logs:[];
  const poses=Array.isArray(state.cameraPoses)?state.cameraPoses:[];
  const poseCount=showRaw?poses.length:Math.min(poses.length,state.trajectoryFilter?.cutIndex??poses.length);
  const selectedIndex=Math.min(trackIndex,Math.max(0,poseCount-1)),selectedPose=poses[selectedIndex];
  const available=representation==='sparse'?!!state.points:representation==='dense'?!!state.densePoints:representation==='splat'?!!(state.splatAvailable||state.splatPoints):!!(state.meshAvailable||state.mesh);
  const label=representation==='sparse'?'Sparse points':representation==='dense'?'Dense points':representation==='splat'?'Gaussian splats':'Mesh';
  const displayStatus=!available?`Waiting for ${representation==='sparse'?'sparse points':representation==='dense'?'dense points':representation==='splat'?'splats':'mesh'}…`:representation==='splat'&&!state.splatAvailable?'Gaussian centers; splat rendering not yet available':assetStatus;
  const copyView=async()=>{
    const live=captureRef.current?.();if(!live){setCopyStatus('View unavailable');return}
    const text=serializeViewInfo({scene:{id:state.sceneId??null,label:state.scenes?.find(s=>s.id===state.sceneId)?.label??null},artifact:{run:state.splatRun??null,checkpoint:state.splatCheckpoint??null,version:state.splatVersion??null},track:{index:selectedPose?selectedIndex:null,source_frame:selectedPose?.sourceFrame??null,timestamp_seconds:selectedPose?.timeSeconds??null},camera:{coordinate_system:'Three.js world',...live.camera},controls:{mode:viewMode,rotation:rotationMode,view:centerMode,pivot_distance:pivotDistance,target:live.target},alignment:{world_from_train:state.worldFromTrain??null,scene_up:state.up??null,correction_pitch_degrees:pitch,correction_roll_degrees:roll,quaternion_xyzw:gravityAlignment(state.up,pitch,roll).toArray()},representation,viewport:live.viewport});
    try{if(!await copyText(text))throw new Error('Clipboard unavailable');setManualCopy('');setCopyStatus('Copied');clearTimeout(copyTimer.current);copyTimer.current=setTimeout(()=>setCopyStatus(''),2000)}catch{setManualCopy(text);setCopyStatus('Select and copy below')}
  };
  const stageName=pipeline?.name||'Waiting for a run';
  const percent=Number.isFinite(pipeline?.total)&&pipeline.total>1&&Number.isFinite(pipeline?.current)&&pipeline.current>=0&&pipeline.current<=pipeline.total?Math.round(pipeline.current/pipeline.total*100):null;
  return <main className="app-shell">
    <header className="app-header"><div className="brand"><div className="brand-mark" aria-hidden="true">S</div><div><strong>SphereDim</strong><span>Reconstruction viewer</span></div></div><div className="header-meta"><div className="run-status"><span className={connected?'status-dot':'status-dot offline'}/><span>{connected?(pipeline?.status==='running'?pipeline.name:'Local preview'):'Reconnecting'}</span></div><button className="drawer-toggle" type="button" aria-pressed={!logOpen} onClick={()=>setLogOpen(false)}>Scene</button><button className="drawer-toggle" type="button" aria-pressed={logOpen} onClick={()=>setLogOpen(true)}>Activity</button><button className="drawer-toggle" type="button" aria-expanded={settingsOpen} aria-controls="settings-drawer" onClick={()=>setSettingsOpen(v=>!v)}>Scene controls</button></div></header>
    {<section className="progress-strip" aria-label="Current activity"><div className="progress-title"><span className="status-dot"/><strong>{stageName}</strong><span>{pipeline?.status==='running'?(pipeline.detail||'In progress'):pipeline?.status==='complete'?'Finished':pipeline?.detail||pipeline?.status||'No current activity'}</span></div>{percent!==null&&<div className="progress-main"><span>{pipeline.current.toLocaleString()} / {pipeline.total.toLocaleString()} · {percent}%</span><Bar value={pipeline.current} total={pipeline.total} label="Current activity progress"/></div>}{pipeline?.status==='running'&&Number.isFinite(pipeline?.etaSeconds)&&pipeline.etaSeconds>=0&&<span className="progress-eta">{duration(pipeline.etaSeconds)} remaining</span>}<button className="drawer-toggle" type="button" onClick={()=>setLogOpen(v=>!v)}>{logOpen?'Close activity':'Activity details'}</button></section>}
    {state.configError&&<p className="error-message" role="alert">{state.configError}</p>}
    {pipeline?.error&&<p className="error-message" role="alert">{pipeline.error}</p>}
    <div className="workspace"><section className="scene-column" aria-label="Reconstruction scene"><div className={`viewport${settingsOpen?' settings-open':''}`} tabIndex={0} aria-label="3D viewport. Drag to orbit, scroll to zoom, and use W A S D to move and Q E for vertical movement while focused." onPointerDown={e=>e.currentTarget.focus({preventScroll:true})} onKeyDown={keyDown} onKeyUp={keyUp} onBlur={()=>keys.current.clear()}><Canvas key={state.sceneId||'default'} dpr={displayDpr} frameloop="demand" gl={{antialias:false}} camera={{position:[4,3,5],fov:55}}><RenderDebug/><DemandInteraction/><AdaptiveCameraDpr displayDpr={displayDpr}/><Scene captureRef={captureRef} state={state} pointSize={pointSize} representation={representation} showRaw={showRaw} onStatus={reportAssetStatus} keys={keys} viewMode={viewMode} selectedPose={selectedPose} pivotDistance={pivotDistance} rotationMode={rotationMode} centerMode={centerMode} onDisengage={disengageTrack} pitch={pitch} roll={roll} savedCamera={savedCamera} selectedIndex={selectedIndex} movementSpeed={movementSpeed} fitScene={!!sceneChoice||Boolean(state.sceneId)}/></Canvas>{state.referenceVideoAvailable&&selectedPose&&<ReferenceFrame sceneId={state.sceneId} label="Reference frame" time={selectedPose?.timeSeconds} visible={showOriginal} onToggle={()=>setShowOriginal(v=>!v)}/>}<div className="view-copy"><button type="button" onClick={copyView}>Copy view info</button><span role="status">{copyStatus}</span>{manualCopy&&<textarea aria-label="View info to copy" readOnly value={manualCopy} onFocus={e=>e.target.select()} onClick={e=>e.target.select()}/>}</div><div className="scene-badge" onPointerDown={e=>e.stopPropagation()}><span className="scene-dot"/><select aria-label="Viewport representation" value={representation} onChange={e=>{setAssetStatus('');setRepresentation(e.target.value)}}>{(state.points||representation==='sparse')&&<option value="sparse">Sparse points</option>}{state.densePoints&&<option value="dense">Dense points</option>}{(state.splatAvailable||state.splatPoints)&&<option value="splat">Gaussian splats</option>}{(state.meshAvailable||state.mesh)&&<option value="mesh">Mesh</option>}</select>{leftTrack&&viewMode==='orbit'&&<span> · Free Roam (left track)</span>}</div><div className="legend"><span>●</span> {selectedPose?'Selected camera':'Latest camera'} <i>━</i> Camera path {centerMode==='pivot'&&viewMode==='orbit'&&<><em>●</em> Orbit pivot</>}</div>{!available&&<div className="empty">{displayStatus}</div>}</div>
      <div className="scene-footer">{<div className="timeline"><div className="timeline-head"><div><strong>Camera path</strong><span>{trajectoryFilterNotice(state.trajectoryFilter,showRaw,poses.length)||'Move through the recorded track'}</span></div><output htmlFor="track-frame">{poseCount?selectedIndex+1:0} <span>/ {poseCount}</span> {Number.isFinite(selectedPose?.timeSeconds)&&<b>{selectedPose.timeSeconds.toFixed(2)}s</b>}</output></div><input id="track-frame" aria-label="Camera path frame" disabled={!poseCount} type="range" min="0" max={Math.max(0,poseCount-1)} step="1" value={selectedIndex} onChange={e=>setTrackIndex(Number(e.target.value))}/><div className="timeline-ends"><span>Start</span><span>End</span></div></div>}</div>
      </section>
      <aside id="settings-drawer" className="inspector" hidden={!settingsOpen} aria-label="Scene controls"><div className="inspector-head"><div><span className="eyebrow">EXPLORE</span><h1>Scene view</h1></div><button className="drawer-close" type="button" aria-label="Close scene controls" onClick={()=>setSettingsOpen(false)}>×</button></div><section className="control-group"><h2>Representation</h2>{state.scenes?.length>1&&<><label className="field-label" htmlFor="scene-choice">Reconstruction</label><select id="scene-choice" value={sceneChoice||state.sceneId||''} onChange={e=>{setSceneChoice(e.target.value);setTrackIndex(0);setShowRaw(false);setAssetStatus('')}}>{state.scenes.map(scene=><option key={scene.id} value={scene.id}>{scene.label}</option>)}</select></>}<label className="field-label" htmlFor="representation">Display as</label><select id="representation" value={representation} onChange={e=>{setAssetStatus('');setRepresentation(e.target.value)}}>{(state.points||representation==='sparse')&&<option value="sparse">Sparse points</option>}{state.densePoints&&<option value="dense">Dense points</option>}{(state.splatAvailable||state.splatPoints)&&<option value="splat">Gaussian splats</option>}{(state.meshAvailable||state.mesh)&&<option value="mesh">Mesh</option>}</select>{displayStatus&&available&&<p className="help-text" role="status">{displayStatus}</p>}</section>
      <section className="control-group"><h2>Mode</h2><div className="mode-switch" role="group" aria-label="Mode"><button type="button" aria-pressed={viewMode==='orbit'} onClick={()=>{keys.current.clear();setViewMode('orbit')}}>Free Roam</button><button type="button" aria-pressed={viewMode==='track'} disabled={!poseCount} onClick={()=>{keys.current.clear();if(savedCamera)savedCamera.used=true;setLeftTrack(false);setCenterMode('point');setViewMode('track')}}>Follow Track</button></div>{viewMode==='track'&&<p className="help-text">Pan or use WASD / Q/E to leave the track.</p>}<div className="camera-controls"><span className="field-label">Rotation</span><div className="mode-switch" role="group" aria-label="Rotation"><button type="button" aria-pressed={rotationMode==='free'} onClick={()=>setRotationMode('free')}>Free Orbit</button><button type="button" aria-pressed={rotationMode==='turntable'} onClick={()=>setRotationMode('turntable')}>Turntable</button></div></div><div className="camera-controls"><span className="field-label">View</span><div className="mode-switch" role="group" aria-label="View"><button type="button" title="Shortcut: 1 when the viewport is focused" aria-pressed={centerMode==='point'} onClick={()=>setCenterMode('point')}>Point View</button><button type="button" title="Shortcut: 2 when the viewport is focused" aria-pressed={centerMode==='pivot'} disabled={viewMode==='track'} onClick={()=>setCenterMode('pivot')}>Pivot View</button></div><p className="control-description">{viewMode==='track'?'Camera stays at the selected track point.':centerMode==='point'?'Look from the current camera position.':'Orbit around an adjustable pivot.'}</p></div>{centerMode==='pivot'&&viewMode==='orbit'&&<div className="pivot-distance"><label htmlFor="pivot-distance">Pivot distance <output htmlFor="pivot-distance">{pivotDistance.toFixed(2)}</output></label><input id="pivot-distance" type="range" min="0.05" max="20" step="0.05" value={pivotDistance} onChange={e=>setPivotDistance(Number(e.target.value))}/><div className="distance-presets"><button type="button" onClick={()=>setPivotDistance(.1)}>Near</button><button type="button" onClick={()=>setPivotDistance(1)}>Default</button><span>Scene units</span></div></div>}</section>
      {<section className="control-group adjustment-group"><h2>Fine tune</h2><SceneAdjustments pointSize={pointSize} setPointSize={setPointSize} movementSpeed={movementSpeed} setMovementSpeed={setMovementSpeed} viewMode={viewMode} showPointSize={representation==='sparse'||representation==='dense'||(representation==='splat'&&!state.splatAvailable)}/></section>}<details className="advanced"><summary>Preview alignment</summary><div className="advanced-content"><p className="help-text">Adjust pitch and roll to level the scene.</p><AlignmentControls pitch={pitch} setPitch={setPitch} roll={roll} setRoll={setRoll} up={state.up}/></div></details><details className="advanced"><summary>View options</summary><div className="advanced-content"><label className="check-row"><input type="checkbox" checked={showRaw} disabled={!Array.isArray(state.rawTrajectory)} onChange={e=>setShowRaw(e.target.checked)}/><span><strong>Show unfiltered path</strong><small>Include positions beyond the cutoff</small></span></label><p className="help-text">{state.up?'Scene aligned to the estimated horizon.':'Scene uses its original orientation.'}</p></div></details>
</aside><div id="activity-drawer" hidden={!logOpen}><LogTail stages={stages} logs={logs} details={state.details||[]} open={logOpen} onClose={()=>setLogOpen(false)} splatRun={state.splatRun} splatCheckpoint={state.splatCheckpoint} denseLabel={state.denseLabel} referenceLabel={state.referenceVideoLabel}/></div></div>
    <footer>Local preview</footer></main>;
}
createRoot(document.getElementById('root')).render(<App/>);
