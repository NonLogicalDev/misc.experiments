# Local reconstruction viewer

Set `SPHEREDIM_STATE` to an atomically published JSON state file and run `./serve-local.sh`. The service binds to `127.0.0.1:5178`; set `SPHEREDIM_PORT` to change the port. Paths in the state resolve relative to the state file. The viewer rereads it for each request and retains the last valid snapshot during a partial write. No recording is uploaded.

The version 1 state contains `trajectory` (`poses`, `points`, and optional `filter` with `cutIndex`, `timeSeconds`, and `reason`), `artifacts` (`splat`, `dense`, and `mesh` descriptors), `reference` (`file` and `label`), `up`, `stages`, `currentActivity` (the selected stage array index or null), `logs` (named file descriptors), and optional `details` strings. A splat descriptor may include `file`, `transform`, `run`, and `checkpoint`; a dense descriptor may include `file`, `label`, and `space` (`train` or `world`). The pose file contains `frames` with `world_from_camera` 3×4 matrices and optional `time_seconds`. The producer owns filtering decisions, stage descriptions, and artifact selection; the viewer does not infer them from a particular run. Missing optional fields are allowed.

The Scene view retains the track scrubber, movement and rotation modes, alignment, and reference picture-in-picture. Activity contains stage history, details, and named logs. The state-selected current activity is summarized above the scene. The full path can be restored in View options.

`tools/run-state/publish.mjs` adapts the existing legacy run configuration and progress files to this contract. Run `node ../run-state/publish.mjs legacy.json viewer-state.json --watch` from this directory to refresh it every two seconds. The adapter selects available artifacts and computes the trajectory filter; it atomically replaces the published state. Run it once without `--watch` for a snapshot. The adapter configuration may include `extraStages`, an ordered array of `{ "name": "Source alignment and color", "statusFile": "source-alignment-status.json", "logFile": "source-alignment.log" }` records; `logFile` is optional. Paths resolve relative to the configuration file. Each status file is a JSON object with `status` (for example `running`, `complete`, or `blocked`) and optional `stage`, `current` (or `done`), `total`, `eta_seconds`, and `error`. Publish status files atomically; omit progress counts when they are not measured. Extra stages appear before legacy stages and can become the current activity.

Run `node test.mjs`, `node test-state.mjs`, `node test-quality.mjs`, `node test-artifacts.mjs`, `node test-camera.mjs`, `node test-track-scrub.mjs`, `node test-rotation.mjs`, `node test-alignment.mjs`, and `node test-motion.mjs`. Build with `SPHEREDIM_STATE=/path/to/state.json npx vite build --configLoader runner`.

A state file can instead be an explicit catalog, for example:

```json
{"version":1,"currentScene":"survey","scenes":[{"id":"survey","label":"Current survey","stateFile":"survey/viewer-state.json"},{"id":"archive","label":"Earlier result","stateFile":"archive/state.json"}]}
```

Each profile is an independent version 1 state file. Paths within it resolve relative to that profile; `stateFile` resolves relative to the catalog. The selected scene supplies its own trajectory, artifacts, reference, activity, and logs. Update the catalog to add or reorder scenes or change the default; no viewer restart is required. Unknown scene IDs are rejected.

## LAN access

Set `SPHEREDIM_HOST=0.0.0.0` when starting the viewer to serve the same state directly on the local network. Open `http://<computer-LAN-address>:5178/` from another device. The default host remains `127.0.0.1`; no pairing proxy is needed.

### Initial view

A scene state may provide `initialView` containing the JSON object from Copy view info (omit its introductory text). The viewer validates it and applies it once when entering that scene. Scene transforms remain authoritative. Follow Track uses the selected recorded position and the supplied orientation; an out-of-range track index is ignored with the entire initial view. These initial control and alignment settings persist like ordinary viewer controls when changing scenes. Without this field the normal scene and camera behavior applies.

### Display parity fixture

`/parity-fixture.html` is a display-only comparison fixture using the viewer's installed Spark renderer. Supply a URL-encoded JSON object in the fragment with `scene` (a catalog scene ID) and `matrix` (16 finite numbers, row-major OpenGL camera-to-world). Keep private case values outside the repository. The scene must point to the PLY being compared; check its hash and transform separately.

The fixture renders 512×512 pixels at DPR 1 with a 55° vertical field of view, near/far 0.1/1000, black background, Spark defaults, sRGB output and ACES filmic tone mapping. Wait for `Ready` after 180 frames before capturing the canvas. It uses the standard viewer PLY endpoint and does not apply scene gravity alignment or the scene transform; supply a camera and model in the same coordinate frame. The fixture omits the app's controls, overlays and adaptive DPR, so matching it does not establish full-app parity. Native and Spark color, encoding and filtering may still differ.
