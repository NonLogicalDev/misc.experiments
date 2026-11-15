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
