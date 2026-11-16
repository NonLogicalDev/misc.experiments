// Scale is arbitrary; detect speeds far outside the run’s robust variation.
export function filterTrajectory(samples, standardDeviations=8) {
  const rawTrajectory=samples.flatMap(s=>s.point);
  const medianOf = values => {const v=[...values].sort((a,b)=>a-b), m=Math.floor(v.length/2);return v.length%2?v[m]:(v[m-1]+v[m])/2;};
  const speeds=[];
  for(let i=1;i<samples.length;i++) {
    const a=samples[i-1], b=samples[i], dt=b.time-a.time;
    speeds.push(Number.isFinite(dt)&&dt>0 ? Math.hypot(...b.point.map((v,j)=>v-a.point[j]))/dt : NaN);
  }
  const valid=speeds.filter(x=>Number.isFinite(x)&&x>1e-9);
  let speedCut=-1, median=null, mad=null, threshold=null;
  if(valid.length>=5) {
    median=medianOf(valid);mad=medianOf(valid.map(x=>Math.abs(x-median)));
    threshold=median+Math.max(standardDeviations*1.4826*mad,3*median);
    const jump=speeds.findIndex(x=>Number.isFinite(x)&&x>threshold);
    if(jump>=0) speedCut=jump+1;
  }
  let boundsCut=-1;
  if(samples.length>=30) {
    const axes=[0,1,2].map(axis=>samples.map(s=>s.point[axis]).sort((a,b)=>a-b));
    const quantile=(v,q)=>{const p=(v.length-1)*q,i=Math.floor(p),f=p-i;return v[i]*(1-f)+v[Math.min(i+1,v.length-1)]*f;};
    const bounds=axes.map(v=>{const lo=quantile(v,.01),hi=quantile(v,.99),margin=Math.max((hi-lo)*.25,1e-6);return [lo-margin,hi+margin];});
    boundsCut=samples.findIndex((s,i)=>i>0&&s.point.some((v,axis)=>v<bounds[axis][0]||v>bounds[axis][1]));
  }
  const candidates=[{index:speedCut,reason:'speed'},{index:boundsCut,reason:'bounds'}].filter(c=>c.index>=0).sort((a,b)=>a.index-b.index);
  if(!candidates.length)return {trajectory:rawTrajectory,rawTrajectory,trajectoryFilter:null};
  const {index:cutIndex,reason}=candidates[0];
  return {trajectory:rawTrajectory.slice(0,cutIndex*3),rawTrajectory,trajectoryFilter:{cutIndex,removedCount:samples.length-cutIndex,timeSeconds:Number.isFinite(samples[cutIndex].time)?samples[cutIndex].time:null,reason,standardDeviations,medianSpeed:median,madSpeed:mad,thresholdSpeed:threshold}};
}
