# Local reconstruction viewer

Set `SPHEREDIM_STATE` to an atomically published JSON state file and run `./serve-local.sh`. The service binds to `127.0.0.1:5178`; set `SPHEREDIM_PORT` to change the port. Paths in the state resolve relative to the state file. The viewer rereads it for each request and retains the last valid snapshot during a partial write. No recording is uploaded.

The version 1 state contains `trajectory` (`poses`, `points`, and optional `filter` with `cutIndex`, `timeSeconds`, and `reason`), `artifacts` (`splat`, `dense`, and `mesh` descriptors), `reference` (`file` and `label`), `up`, `stages`, `currentActivity` (the selected stage array index or null), `logs` (named file descriptors), and optional `details` strings. A splat descriptor may include `file`, `transform`, `run`, and `checkpoint`; a dense descriptor may include `file`, `label`, and `space` (`train` or `world`). The pose file contains `frames` with `world_from_camera` 3×4 matrices and optional `time_seconds`. The producer owns filtering decisions, stage descriptions, and artifact selection; the viewer does not infer them from a particular run. Missing optional fields are allowed.

The Scene view retains the track scrubber, movement and rotation modes, alignment, and reference picture-in-picture. Activity contains stage history, details, and named logs. The state-selected current activity is summarized above the scene. The full path can be restored in View options.

`tools/run-state/publish.mjs` adapts the existing legacy run configuration and progress files to this contract. Run `node ../run-state/publish.mjs legacy.json viewer-state.json --watch` from this directory to refresh it every two seconds. The adapter selects available artifacts and computes the trajectory filter; it atomically replaces the published state. Run it once without `--watch` for a snapshot.

Run `node test.mjs`, `node test-state.mjs`, `node test-quality.mjs`, `node test-artifacts.mjs`, `node test-camera.mjs`, `node test-track-scrub.mjs`, `node test-rotation.mjs`, `node test-alignment.mjs`, and `node test-motion.mjs`. Build with `SPHEREDIM_STATE=/path/to/state.json npx vite build --configLoader runner`.
