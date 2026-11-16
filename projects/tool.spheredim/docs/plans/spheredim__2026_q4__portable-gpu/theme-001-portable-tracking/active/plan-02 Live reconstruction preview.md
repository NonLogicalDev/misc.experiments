# Live reconstruction preview

Build a local React Three Fiber preview that reads the existing progress, camera poses, and sparse point cloud while tracking runs. Show processing status and trajectory in 3D, handle incomplete or unavailable snapshots, and avoid uploading recordings or generated data. Reuse the existing SphereDim pipeline and keep frontend build dependencies procurable rather than committing binaries or generated bundles. Verify the running preview against the real recording outputs and document how to start it.

- Status: active.
- Worker: `/root/live_tracking` is preparing an isolated frontend and local server; the owner will integrate and verify it.

- 2026-11-15: React Three Fiber preview runs locally with tracking and training progress, logs, real Gaussian rendering and a representation selector. Added robust relative-speed and percentile-bounds filtering while retaining the raw trajectory. The user requested point sizing, WASD, tracked-camera timeline, resizable original-frame picture-in-picture, and adjustable pivot with presets. User feedback: the initial UI exposes debug data and lacks a pleasant product experience; redesign around the scene, clear exploration controls, restrained status, and optional diagnostics. `/root/live_tracking` owns viewer work and visual verification.

- 2026-11-15: The user refined the camera interaction into three distinct dimensions: movement (Free Roam / Follow Track), rotation (Free Orbit / Turntable), and center (Point View / Pivot View). Follow Track selects Point View; the manual path slider remains visible and changes position without changing current orientation. Panning or translating switches to Free Roam. Keep shortcuts coherent, disable autoplay, preserve original-frame resizable PiP, docked space-partitioning drawers, compact layout, prominent progress, and Leva settings.

- 2026-11-15: User corrected the reference-video choice: the picture-in-picture must use horizon-leveled footage with camera yaw preserved. An initial viewer reference used the unstabilized panorama, contrary to that requirement. Use the stabilized masked panorama by default and label the reference; preserve matching timestamps and never turn on direction lock.
