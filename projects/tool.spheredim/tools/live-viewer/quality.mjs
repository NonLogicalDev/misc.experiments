export function splatDescription(run, checkpoint) {
  return run && checkpoint ? `Displayed splat: ${run} · ${checkpoint}` : null;
}

export function trajectoryFilterNotice(filter, showRaw, poseCount) {
  if (showRaw || !filter || !Number.isInteger(filter.cutIndex) || filter.cutIndex < 0 || filter.cutIndex >= poseCount) return null;
  const count = poseCount - filter.cutIndex;
  const time = Number.isFinite(filter.timeSeconds) ? ` at ${filter.timeSeconds.toFixed(1)}s` : '';
  const reason = filter.reason === 'speed' ? 'relative motion outlier' : filter.reason === 'bounds' ? 'position outlier' : 'outlier';
  return `${count} later ${count === 1 ? 'position hidden' : 'positions hidden'} after a ${reason}${time}. Show the full path in View options.`;
}
