# Portable GPU tracking

- Status: active; Apple GPU prototype installed and image-accuracy target not yet met.
- Goal: run 360DVO on Apple and AMD GPUs without its CUDA-only extensions and retain spherical input and usable poses.
- Next action: investigate low-texture failure and image alignment, add confidence/failure reporting and seam/long-video tests, and validate and package AMD ROCm on suitable hardware.
- [Plan](active/plan-01%20Portable%20360DVO.md) · [Owners](../OWNERS.md)

## Workers

- /root/kernel_audit: complete; audited geometry and bundle adjustment, with depth update, fixed calibration and Cholesky findings corrected by the owner.
- /root/layer_packaging: complete; the real port layer was integrated and checked. Source is now fetched at its pinned revision rather than from a bundled archive.

- Live 3D preview: active; `/root/live_tracking` is preparing a React Three Fiber viewer. [Plan](active/plan-02%20Live%20reconstruction%20preview.md).
- Dense points, splats, and meshes: active research; `/root/insv_research` is evaluating native 360 approaches and GPU portability. [Plan](active/plan-03%20Dense%20scene%20reconstruction.md).

- Current quality work: active operator mask development (/root/insv_research); SfM quality investigation and rerun preparation (/root/dense_native); splat diagnosis and evaluation (/root/artifact_audit). The full SfM run remains paused until the tighter mask is validated.

- Quality audit complete; Terra implementation pending; audit integrated by `/root`; [plan 04](active/plan-04%20Reconstruction%20quality%20implementation.md). Corrected 138-frame mask comparison and paired 3k-step splat comparison completed; quality remains insufficient. Implementation is pending the audit handoff, with native ERP renderer/mask regressions before new long runs.
