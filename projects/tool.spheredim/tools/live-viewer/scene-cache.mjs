export function reuseSceneData(previous,next) {
  if(next.sceneId!==previous.sceneId) return next;
  if(next.poseVersion&&next.poseVersion===previous.poseVersion) { next.rawTrajectory=previous.rawTrajectory; next.cameraPoses=previous.cameraPoses; }
  if(next.trajectoryVersion&&next.trajectoryVersion===previous.trajectoryVersion) next.trajectory=previous.trajectory;
  if(next.pointsVersion&&next.pointsVersion===previous.pointsVersion) next.points=previous.points;
  if(next.denseVersion&&next.denseVersion===previous.denseVersion) next.densePoints=previous.densePoints;
  return next;
}

export function reconcileSceneChoice(choice,snapshot) {
  if(!choice||snapshot?.configError||!Array.isArray(snapshot?.scenes)) return choice;
  return snapshot.scenes.some(s=>s.id===choice) ? choice : (snapshot.sceneId ?? '');
}
