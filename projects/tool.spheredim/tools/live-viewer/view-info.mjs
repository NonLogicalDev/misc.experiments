// Keep the report compact and explicit about coordinate and quaternion conventions.
export function serializeViewInfo({scene,artifact,track,camera,controls,alignment,representation,viewport}) {
  return 'SphereDim view info (v1)\n'+JSON.stringify({schema:'spheredim-view-info-v1',scene,artifact,track,camera,controls,alignment,representation,viewport},null,2);
}

export function validateInitialView(v) {
  const c=v?.camera, o=v?.controls;
  const vector=(a,n)=>Array.isArray(a)&&a.length===n&&a.every(Number.isFinite);
  if(v?.schema!=='spheredim-view-info-v1'||!vector(c?.position,3)||!vector(c?.quaternion_xyzw,4)||!vector(c?.up,3)||!vector(o?.target,3)) return null;
  const norm=Math.hypot(...c.quaternion_xyzw);
  if(norm<1e-8||Math.hypot(...c.up)<1e-8||!Number.isFinite(c.fov_degrees)||c.fov_degrees<=0||c.fov_degrees>=180||!Number.isFinite(c.near)||!Number.isFinite(c.far)||c.near<=0||c.far<=c.near) return null;
  if(!['orbit','track'].includes(o.mode)||!['free','turntable'].includes(o.rotation)||!['point','pivot'].includes(o.view)||!Number.isFinite(o.pivot_distance)||o.pivot_distance<.05||o.pivot_distance>20||!['sparse','dense','splat','mesh'].includes(v.representation)) return null;
  if(o.mode==='track'&&(!Number.isInteger(v.track?.index)||v.track.index<0||o.view!=='point')) return null;
  return {...v,camera:{...c,quaternion_xyzw:c.quaternion_xyzw.map(x=>x/norm)}};
}

export function initialViewReady(v,mode,rotation,view,index) {
  return !!v && v.controls.mode===mode && v.controls.rotation===rotation && v.controls.view===view && (mode!=='track'||v.track.index===index);
}

export function initialViewForPoseCount(view,count) {
  return view?.controls.mode==='track' && view.track.index>=count ? null : view;
}
