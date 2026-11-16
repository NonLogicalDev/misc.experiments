// Keep the initial display density as the restoration target; never derive it from a reduced frame.
export function cameraDprPolicy(displayDpr, settleMs=200) {
  const full=Math.max(1,Math.min(2,displayDpr));
  let previous=null,lastMove=-Infinity;
  return (position,quaternion,now)=>{
    const current=[...position,...quaternion];
    if(previous&&current.some((value,i)=>Math.abs(value-previous[i])>1e-7))lastMove=now;
    previous=current;
    return now-lastMove<settleMs?1:full;
  };
}
