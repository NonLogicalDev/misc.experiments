# Scope and guidance

Follow [owner authorization](OWNERS.md), the user's global instructions, and current project instructions. Port 360DVO to execute on Apple and AMD GPUs without its CUDA-specific extensions, preserving full equirectangular input. Use layerctl to keep upstream provenance and the port layer reproducible. CPU is a validation reference; GPU execution is the goal. Validate native GPU behavior, kernel correctness, Blender-compatible output, and trajectory/image accuracy on existing diverse test scenes. Do not infer AMD support from Apple tests. Preserve existing SphereDim and do not publish. Record decisions and checks in the [active plan](theme-001-portable-tracking/active/plan-01%20Portable%20360DVO.md).

For Insta360 footage, preserve yaw while leveling the horizon, and exclude the operator before reconstruction. Keep masks aligned to the input video and report coverage and orientation limitations. Use app-free export where feasible; do not claim camera IMU orientation is a measured translation or drift-free ground truth.

Any upstream fork or modification must use layerctl with pinned source and a separate maintained patch layer. Keep layerctl external; do not vendor or submodule the tool. Reconstruction exports must preserve observed source pixels and explicit validity rather than fill or cosmetically warp unsupported content. See the Terra quality plan for source-observation, lens-provenance and validation requirements.

Use Terra subagents for cheap routine checks and bounded implementation tasks; keep research judgments and final integration with the owner. Preserve the separate viewer worker.
