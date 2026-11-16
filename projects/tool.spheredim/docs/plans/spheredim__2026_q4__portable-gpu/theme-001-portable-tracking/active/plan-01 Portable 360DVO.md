# Portable 360DVO

## Purpose and scope

Port the published 360DVO implementation to Apple and AMD GPUs without CUDA-only kernels. Keep full spherical images and existing SphereDim exports. Use layerctl to preserve a pinned upstream and changes. [Owners](../../OWNERS.md). No publication or unrelated changes.

## Completion criteria

- [ ] Pinned upstream and portable changes are materialized reproducibly with layerctl and hash-verified dependency procurement.
- [ ] GPU tensor replacements are checked against the original kernel mathematics and finite differences; CPU and Apple MPS results agree within documented tolerance.
- [x] The actual pretrained model runs through video, tracking, exported poses, and Blender import on Apple GPU.
- [ ] Compare trajectory and image alignment against existing Blender scenes and trajectory against real footage; report accuracy failures instead of hiding them.
- [ ] Document AMD ROCm requirements and what was and was not tested on actual AMD hardware.

## Current state

The Apple MPS inference port and offline installation are in the project. Operator references and Blender imports passed, but the per-frame image target fails and the low-texture scene fails badly. AMD ROCm portability is unverified on hardware and its runtime is not vendored. The seam, long clips and confidence reporting remain open. CPU is a numerical reference.

## Work log

- 2026-11-14: User requested GPU execution, Apple and AMD compatibility, kernel recoding, layerctl, and Tasker_Stream records under `docs/plans`. Upstream was cloned at `46f5ed0735d39aff29a75f28c360600340879b35`; pretrained weights were retrieved. An initial Apple MPS run produced 48 poses but failed accuracy at 256 px. Spherical pose Jacobians were checked against finite differences, which exposed and corrected an adjoint-convention mismatch. The port is still uncheckpointed in the temporary checkout; next: check kernel math and layer packaging, then rerun GPU accuracy at useful resolution.

- 2026-11-14: Assigned /root/kernel_audit a read-only kernel and Jacobian audit and /root/layer_packaging isolated layerctl preparation. The owner retains integration and GPU testing.

- 2026-11-14: Kernel audit found depth update, fixed-intrinsics and failure-reporting mismatches; owner corrected these and independently checked spherical pose and depth Jacobians. Five operator tests passed on Apple MPS. Offline layerctl composition passed with a fixture, pending the real port. A pre-fix 1024-pixel MPS run imported 48 poses into Blender and measured 0.154% trajectory RMS and 1.676% worst-frame image p95; a corrected run is underway. This does not establish accuracy across footage.

- 2026-11-14: Integrated the port under `vendor/360dvo-port`. Actual layer patch passed `layerctl check` and fresh projection. Vendored Apple Python 3.14 wheels and upstream checkpoint, with hashes; a clean offline install and seven Apple GPU operator tests passed from the project-local projection. Source checkpoint `1b56365260b94df484d99d6baa2327e60fb3e412`; layer definition checkpoint `48a5d23575111033bb40c341092f42bb75e240c9`. Corrected 1024-pixel loop: 0.153% path-normalized position RMS; 1.669% worst-frame image p95, so image target fails. Bridge night 0.369% and grove 0.115% position RMS against dataset pseudo-ground-truth after similarity alignment. Indoor and additional synthetic comparisons are underway. AMD runtime wheels and hardware validation remain open. The spherical seam treatment is inherited and unverified.

- 2026-11-14: The installed project backend processed the dynamic Blender scene (32 poses, 0.145% trajectory RMS and 1.270% worst-frame image p95) and plain low-texture scene (24 poses, 3.332% trajectory RMS and 32.791% worst-frame image p95). Both failed the image criterion; complete output does not imply accuracy. The indoor RC-car reference comparison was 0.077% trajectory RMS. Results and matrices are in `validation/portable-360dvo`; source-linked research is in `docs/research/native-360-tracking.md`. Continue with confidence/failure reporting, seam tests, improved alignment, long clips, and actual AMD support; do not call the goal complete.

- 2026-11-15: Moved SphereDim into `misc.experiments/projects/app.spheredim`, retaining its Git history as a merge parent. The existing local environments and layerctl projection were moved and had their paths repaired.

- 2026-11-15: Replaced tracked binary wheels, weights, generated media and binary source fixtures with hash-verified download or regeneration instructions. Source is fetched by the pinned 360DVO layer. Repaired imported SphereDim history to remove the binary artifacts while preserving the existing misc.experiments parent and unrelated work.

- 2026-11-15: Renamed the project to `misc.experiments/projects/tool.spheredim`; repaired local environment and layerctl projection paths.

- 2026-11-15: Flattened the layer definition paths under `vendor/360dvo-port/layers/`; the definition repository root is `vendor/360dvo-port`.

- 2026-11-15: Replaced the copied COLMAP and FFmpeg source trees with submodules pinned to their corresponding release commits; binary runtime downloads remain hash-verified.

- 2026-11-15: Migrated SphereDim CPU and GPU setup and validation commands to uv. A fresh hash-locked GPU installation passed seven Apple MPS tests; a fresh CPU environment passed seven tests; an incorrect wheel hash was rejected. AMD remains unverified.

- 2026-11-15: Added an app-free INSV exporter using insta360-rs on GPU, with FlowState horizon leveling and preserved heading by default. A one-second X5 test preserved audio. For the real recording, use an operator mask before tracking; a camera-relative mask and a frame-aligned moving mask are being prepared. Orientation is estimated, not ground truth. Apple GPU tracking and Blender output remain under evaluation; the operator mask has only been visually checked on sampled frames.

- 2026-11-15: Added a pinned Rust X5 IMU/orientation extractor and scripts to map a camera-relative mask and tracking rotations to a FlowState panorama with rolling-shutter correction off. The fused stream exactly reproduced the local extractor output for the real recording; a short panorama ray-map check passed. Heading remains relative, and Blender overlay and full-video mask coverage still require verification.

- 2026-11-15: One-second sampling exposed an operator-mask miss near the end. Stopped tracking before that section, expanded the mask from 40% to 75% for the final three seconds, and restarted on the revised video. Reviewed samples are not proof of full-frame coverage; the heavily masked tail may be weakly constrained.

- 2026-11-15: Compared the IMU-predicted OFF-to-FlowState spherical remap to the actual no-rolling-shutter export at 0, 10, 20, 30, 40, 50, 60 and 70 seconds of the X5 recording. Mean RGB differences after resizing to 1024×512 ranged from 1.29 to 2.14 on an 8-bit scale. This checks the stabilization mapping, not 3D trajectory or reprojection accuracy. A limited-range mask-compositing bug was caught visually and corrected with opaque RGB masking; the corrected 2162-frame export preserves 72.138733 seconds and the source audio.

- 2026-11-15: Ran the masked X5 clip end to end on Apple MPS: 433 sampled poses and 35,712 sparse points. Blender reopened the full result with the stabilized masked video at 30000/1001 fps. Validation found large trajectory jumps beginning near 70 seconds after the mask expanded to 75%: the worst adjacent translation step was 40.87 arbitrary units versus a 0.204 median, and the worst adjacent IMU rotation disagreement was 45.54 degrees. The full result is unreliable at the end; a separate 414-pose Blender scene stops before 69 seconds and uses the earlier 34,464-point snapshot. Accuracy and full mask coverage remain unverified, and no surface mesh was reconstructed. Opened the shorter scene in Blender at the user’s request.

- 2026-11-15: Tested Spirula native spherical SfM with 120 masked 1024×512 panoramas and GPU SIFT. Output cameras are COLMAP ID 17 EQUIRECTANGULAR with source filenames preserved. The result is partial: two disconnected components contain 37 and 55 distinct images (92/120 total); 28 are unregistered and there are no shared images between components. Their reported mean reprojection errors are 0.546 and 0.444 pixels, which do not prove trajectory accuracy. Separate similarity comparisons to 360DVO are cross-method checks, not ground truth. Models and logs were preserved with the recording.

- 2026-11-15: Two isolated SfM resume/bridge tests left the same disconnected components and 92/120 coverage. Component 0 spans approximately 0.50–22.02 seconds, component 1 approximately 26.53–66.57 seconds, with no shared images. A successful command exit is not a successful merge.

- 2026-11-15: Native SfM comparison on the same 120 timestamped panoramas registered 109/120 unique frames in two disconnected components (70 and 39) for horizon-leveled input, versus 92/120 (37 and 55) for camera-relative input. The primary component mean reprojection was 0.437 vs 0.546 px, but components contain different images; stabilized masks also had an extra four-pixel guard and reprojection/encoding differed. This supports a coverage benefit in this test, not an isolated causal or accuracy proof. A full 2,162-frame 2048×1024 horizon-leveled masked run is in preparation.

- 2026-11-15: User directed continued work until SfM and splat quality are good. The all-frame run is paused after feature extraction began because the existing operator mask discarded too much scene. /root/insv_research is developing and checking a tighter moving mask; /root/dense_native is evaluating pose quality and preparing a native full-panorama rerun. Use the clean horizon-leveled, yaw-preserved export with a validated operator mask, and report registration, connectivity, reprojection and independent accuracy limits.
