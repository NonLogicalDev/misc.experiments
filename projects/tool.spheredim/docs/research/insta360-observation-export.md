# Insta360 observation export for reconstruction

Status: source audit and proposed work; the observation sidecar and reconstruction-safe export described here are **not implemented or validated**. The goal is one native equirectangular reconstruction input with traceable measured observations, preserving the existing app-free workflow and horizon leveling with yaw retained. Perspective-view extraction is out of scope.

## What the current exporter does

[`scripts/stitch_insv.py`](../../scripts/stitch_insv.py) uses `insta360-rs==0.2.1`, requests the GPU backend, and defaults to FlowState, 2048 × 1024, and rolling-shutter correction off. It does not explicitly choose a seam mode or export ray provenance. The inspected upstream source defaults to a fixed seam. The output is a stitched video; it does not establish that every pixel corresponds to a single physical ray.

This audit inspected the [OpenSpeleo/insta360-rs source at commit `b4f3845`](https://github.com/OpenSpeleo/insta360-rs/tree/b4f3845feb105b70c1928ed4316fe1d8a963bc36), which identifies itself as version 0.2.1. The installed Python wheel's source commit and build features have **not** been verified. Do not assume the wheel is identical to that checkout: record its package hash, provenance, source commit and build features before relying on these findings. The project's [export notes](../insta360-export.md) describe the tested workflow and its limitations.

The inspected source exposes resolved per-lens calibration, including projection parameters, orientation, translation and FOV/blend information. Its [GPU projection](https://github.com/OpenSpeleo/insta360-rs/blob/b4f3845feb105b70c1928ed4316fe1d8a963bc36/src-rust/stitch_gpu.wgsl) maps panorama directions into lens images, clips invalid projections and computes weights. The fixed stitch projection files inspected do not reference the stored lens translations. Their presence in calibration does not mean that the stitch accounts for depth-dependent parallax.

The Rust [`stitch::diagnostics::inspect`](https://github.com/OpenSpeleo/insta360-rs/blob/b4f3845feb105b70c1928ed4316fe1d8a963bc36/src-rust/stitch/diagnostics.rs) produces source masks and lens ownership and weight images. It is a CPU diagnostic before motion and seam optimization, not an output-aligned provenance stream; the inspected Python API does not expose it. Its blue ownership channel represents zero total detail weight. That is not sufficient evidence that the optical scene is physically unobserved.

## Preserve measurements

- A lens may cover more than 180 degrees, so the overlap between lenses is not automatically a blind strip. Actual support depends on the recording's calibration, image crop, lens and housing masks, and sampling boundaries. Preserve usable overlap.
- Resampling a calibrated source observation onto the spherical output is acceptable when the exact source location and geometry remain traceable. Do not inpaint missing regions or use unconstrained optical flow, stretching, or blending of incompatible surfaces to conceal the seam for reconstruction.
- Select one real lens observation deterministically where a single-valued panorama is needed. Record which lens supplied it and its source coordinates. A lens switch can still leave a discontinuity due to parallax; choosing a source does not solve geometric alignment. Preserve both underlying lens observations and their separate mappings for diagnostics and future direct use.
- Keep distinct reason codes or masks for no calibrated source support, uncertain/disagreeing overlap, and operator exclusion. Use tightly measured exclusions only where necessary. A confidence score is not proof that a pixel depicts the correct surface.
- Lens centers are separated. A nearby scene point therefore projects along rays with different origins; a single central panorama cannot represent both observations exactly at every depth. A general ray model needs each observation's calibrated origin and direction. Exact physical units, reference frame, conventions and accuracy of the recorded translations must be verified; do not claim metric origins until then.

## Proposed exporter extension

Modify the pinned exporter through layerctl: preserve upstream provenance, keep authored patches in a separate project layer and rebuild from a fresh composition. Keep layerctl external rather than vendoring or submoduling it. Preserve original recordings. Add an optional lossless, timestamped observation sidecar matched to the panorama dimensions and frame presentation timestamps, containing:

1. Per-lens predicted support before blend weights, including source bounds, calibration masks, and sampling validity; identify which checks are geometry predictions rather than verified physical visibility.
2. Per-lens source coordinates, calibrated ray direction and lens-origin data, with coordinate conventions, calibration and source identifiers, validity and precision documented. Where a blended or warped pixel has multiple contributors, retain all contributors and weights or explicitly mark the mapping ambiguous; do not fabricate one source coordinate.
3. The selected real source for any reconstruction-safe single-source panorama, and separate overlap disagreement and operator masks. Avoid discarding valid data merely because it lies in the overlap.
4. Exact output pixel-center convention, calibration version and resolved parameters, source lens ordering, original frame identifiers and timestamps, per-frame stabilization transform, rolling-shutter behavior and the actual seam/warp transform. The metadata must represent the transforms **actually applied**, not a separately estimated approximation. Include unknown and unsupported values explicitly.

Use the exporter's actual GPU mapping path and capture its post-transform mapping. A static CPU diagnostic, a frame-level rotation when rolling-shutter correction is active, or an independently rounded timeline cannot substitute for that mapping. Keep sidecar artifacts out of Git and avoid storing duplicate raw video.

## Audit the visible doorframe shear

1. Trace the same doorframe and nearby features to each original lens at matched presentation timestamps, then compare to the existing export. Record source identifiers, calibration selection, housing/accessory settings and image crop. Verify timing; a paired container alone does not prove physical capture synchronization.
2. Compare with stabilization and rolling-shutter settings under controlled conditions. Determine whether misalignment changes with scene depth, camera motion or time. Different behavior suggests parallax, temporal offset, readout or calibration error, but does not prove any cause alone.
3. Measure reprojection and edge-continuity residuals in overlap. Produce a narrow uncertainty mask where source observations cannot be reconciled and select a real source elsewhere. Do not fill the seam or average incompatible surfaces to make the picture look continuous.
4. Compare depth-aware or other constrained correction only if it is supported by measured scene geometry and its source-ray mapping is retained. Upstream also exposes dynamic and optical-flow seam modes, but their visual alignment is not evidence of reconstruction-safe geometry; do not enable them by default or claim they preserve observations without verifying their transformations and downstream effect.

## Acceptance checks

- Synthetic calibrated lens cases cover disjoint, touching and overlapping support, image crop, mask edges, lens order, panorama longitude wrap, poles, stabilization and changing orientation. Confirm known support union and intersection, subpixel mapping and source identity.
- Match sidecars to output frame timestamps and compare their coordinates and flags against the actual rendering path for fixed-seam exports and each supported motion/readout configuration. Fail explicitly when the mapping or calibration is unknown.
- On representative original recording frames, inspect support and disagreement overlays against both source lenses, including the reported doorframe and multiple depths and camera motions. Confirm retained overlap and that exclusions are as narrow as the evidence supports.
- Compare native spherical feature matches and reconstruction residuals with the current export. Check that visible seam reduction has not come from invented or blended geometry, and report remaining parallax and uncertain areas. No quality improvement is established until these checks are run.
