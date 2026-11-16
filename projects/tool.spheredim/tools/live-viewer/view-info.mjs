// Keep the report compact and explicit about coordinate and quaternion conventions.
export function serializeViewInfo({scene,artifact,track,camera,controls,alignment,representation,viewport}) {
  return 'SphereDim view info (v1)\n'+JSON.stringify({schema:'spheredim-view-info-v1',scene,artifact,track,camera,controls,alignment,representation,viewport},null,2);
}
