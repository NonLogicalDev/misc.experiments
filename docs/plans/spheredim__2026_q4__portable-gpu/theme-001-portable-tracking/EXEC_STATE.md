# Portable GPU tracking

- Status: active; Apple GPU prototype installed and image-accuracy target not yet met.
- Goal: run 360DVO on Apple and AMD GPUs without its CUDA-only extensions and retain spherical input and usable poses.
- Next action: investigate low-texture failure and image alignment, add confidence/failure reporting and seam/long-video tests, and validate and package AMD ROCm on suitable hardware.
- [Plan](active/plan-01%20Portable%20360DVO.md) · [Owners](../OWNERS.md)

## Workers

- /root/kernel_audit: complete; audited geometry and bundle adjustment, with depth update, fixed calibration and Cholesky findings corrected by the owner.
- /root/layer_packaging: complete; verified offline layerctl composition with a fixture; owner must replace fixture with the real port and rerun checks.
