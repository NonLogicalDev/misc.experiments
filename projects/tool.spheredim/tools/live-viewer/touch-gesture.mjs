// Reset the gesture baseline whenever fingers join or leave.
export function touchGesture(){
  const points=new Map();let prior=null;
  const measure=()=>{const values=[...points.values()],center={x:values.reduce((a,p)=>a+p.x,0)/values.length,y:values.reduce((a,p)=>a+p.y,0)/values.length};return {center,span:values.length===2?Math.hypot(values[0].x-values[1].x,values[0].y-values[1].y):null}};
  return {
    down(id,x,y){points.set(id,{x,y});prior=measure();return points.size},
    move(id,x,y){if(!points.has(id))return null;points.set(id,{x,y});const next=measure(),result={count:points.size,from:prior.center,to:next.center,scale:prior.span>0&&next.span>0?next.span/prior.span:1};prior=next;return result},
    up(id){points.delete(id);prior=points.size?measure():null;return points.size},
    clear(){points.clear();prior=null},ids(){return [...points.keys()]}
  };
}
