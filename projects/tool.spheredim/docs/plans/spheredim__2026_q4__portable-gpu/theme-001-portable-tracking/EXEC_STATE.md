# Portable GPU tracking

- Status: active; Apple GPU prototype installed and image-accuracy target not yet met.
- Goal: run 360DVO on Apple and AMD GPUs without its CUDA-only extensions and retain spherical input and usable poses.
- Next action: investigate low-texture failure and image alignment, add confidence/failure reporting and seam/long-video tests, and validate and package AMD ROCm on suitable hardware.
- [Plan](active/plan-01%20Portable%20360DVO.md) · [Owners](../OWNERS.md)

## Current execution: larger physical-lens reconstruction

- `/root`: larger-run integration complete. All 276 physical-lens observations across 138 timestamps registered, producing 24,614 points. The former 27.4° adjacent rotation discrepancy fell to 1.3° with broader coverage; global orientation disagreement remains.
- `/root/terra_sample_quality`: paired image comparison complete. The 10,000-step run improved 33 of 36 held-out views: mean spherical PSNR 21.87 → 23.54 dB, SSIM 0.782 → 0.850, gradient ratio 0.622 → 0.750. Doorway geometry and detail remain poor. These views participated in SfM and were held out only from splat training.
- `/root/terra_handoff_check`: viewer verification complete. Port 5178 remains available; live state selects the final 10,000-step artifact, and separate 3,000/10,000-step scenes preserve their own pose/point files. Image comparison is finished; no reconstruction-quality acceptance is claimed.
- `/root/terra_export_baseline`: independent review complete. The runner now rejects incomplete checkpoint payloads, including stable paused writes; nine focused runner tests passed. The current run was not interrupted, and its saved checkpoint passed the stricter checker.
- The bounded training run took 802 seconds and produced 232 MB. Free disk remained about 37 GiB, above the 35 GiB reserve. No training process remains active.
- Pending quality work: original training-camera render evaluation with original camera-indexed appearance state; localized pose/geometry diagnosis around the doorway; controlled resolution and renderer checks. Additional training alone is not an accepted fix. See [quality plan](active/plan-04%20Reconstruction%20quality%20implementation.md) and [comparison report](../../../research/rig-sfm-comparison.md).
- Older entries below are execution history, not current worker assignments.

## Workers (history)

- /root/kernel_audit: complete; audited geometry and bundle adjustment, with depth update, fixed calibration and Cholesky findings corrected by the owner.
- /root/layer_packaging: complete; the real port layer was integrated and checked. Source is now fetched at its pinned revision rather than from a bundled archive.

- Live 3D preview: active; `/root/live_tracking` is preparing a React Three Fiber viewer. [Plan](active/plan-02%20Live%20reconstruction%20preview.md).
- Dense points, splats, and meshes: active research; `/root/insv_research` is evaluating native 360 approaches and GPU portability. [Plan](active/plan-03%20Dense%20scene%20reconstruction.md).

- Current quality work: active operator mask development (/root/insv_research); SfM quality investigation and rerun preparation (/root/dense_native); splat diagnosis and evaluation (/root/artifact_audit). The full SfM run remains paused until the tighter mask is validated.

- Quality audit complete; Terra implementation pending; audit integrated by `/root`; [plan 04](active/plan-04%20Reconstruction%20quality%20implementation.md). Corrected 138-frame mask comparison and paired 3k-step splat comparison completed; quality remains insufficient. Implementation is pending the audit handoff, with native ERP renderer/mask regressions before new long runs.

## Current assignments (2026-11-15 evening)

Earlier worker entries above are historical. Active `/root/terra_viewer_quality` owns the generic state consumer and Scene/Activity UI; active `/root/terra_splat_perf` diagnoses splat performance read-only. `/root/terra_export_baseline` completed the three-timestamp source observation audit. `/root` owns integration and the reconstruction quality plan; no new long training job is running.

- Current viewer increment complete, local checkpoint `e1c33d98c99ac85753a70307e810451f5e19a775`. Active `/root/terra_sample_quality` checks fidelity at matched path samples; active `/root/terra_export_baseline` builds an observation-only seam-cutout sample; `/root` integrates. Viewer service remains running.

## Current execution, 2026-11-15 18:45 PST

- Active `/root/terra_export_baseline`: independently projected camera-frame lens probes and a corrected-color aligned preview; actual X5 embedded V6 calibration verified. Active `/root`: fit one fixed inter-lens rotation and check held-out frames. User explicitly requests alignment before a new video preview; wider masks alone do not satisfy this.
- `/root/terra_sample_quality`: completed the 3k + 3k native GPU no-warp comparison. Removing three suspect poses did not improve mean held-out PSNR/SSIM; do not promote the exclusion as a quality fix. Both checkpoints and identical-reference comparisons are preserved beside the recording.
- `/root/terra_live_progress`: completed configurable extra stages in the state producer; Source alignment and color is visible on the running viewer.
- `/root/terra_handoff_check`: completed pinned Spirula source composition and verified-toolchain configuration; 1,210 shader blobs, no GPU regression build launched. A correct calibration-warp fix needs explicit ERP camera context; no blind global wrap patch.

## Current rig experiment

- Active `/root`: paired zero-baseline/separated-baseline global SfM on the same 16 timestamps, native spherical measurements, fixed relative rotation, identical masks and withheld feature regions; bounded run and result integration.
- `/root/terra_export_baseline`: complete; synchronized nominal-body ERP lens pairs and support masks exported with verified hashes/PTS, 52 MiB.
- Active `/root/terra_sample_quality`: rig dataset, inverse orientation mapping for reviewed operator masks, mask review sheets and physical/zero rig manifests.
- Active `/root/terra_handoff_check`: independent held-out spherical feature tracks and geometry comparison. Known SfM global rig support verified from pinned source/CLI; run accuracy still pending.
- Viewer remains available on port 5178; free disk last verified 38 GiB. No long training run is active. User's new two-physical-camera permission supersedes the earlier one-observation-per-timestamp restriction; no virtual perspectives/cube faces remain allowed.

## Computed baseline and orientation constraints

- Computed separation tested in four controlled native GPU arms; see [rig comparison](../../../research/rig-sfm-comparison.md). No clear held-out quality improvement. Frame930 remains rotationally inconsistent in the models that register it.
- Stock INSV telemetry run failed to calibrate mapping priors and later rescaled fixed baseline while leveling.
- Active `/root/terra_handoff_check`: layerctl patch for explicit soft rotation priors and fixed-rig scale preservation; bounded standalone GPU SfM build.
- Active `/root/terra_sample_quality`: fused orientation to camera-basis CSV adapter, provenance and tests.
- Active `/root`: integration, paired GPU validation, report, progress and disk monitoring. Viewer5178 confirmed200; free disk38GiB before boundedbuild.

## Current execution after workflow-status repair

- Active /root: integrate explicit orientation priors, audit the completed 1°, 0.5° and 0.25° GPU trials, and review broader reconstruction inputs. The final bundle adjustment now includes all 16 body poses and all 15 orientation factors; registration alone does not establish accuracy.
- Active /root/terra_handoff_check: audit residual math and orientation-constraint weighting. The 0.25° trial still disagrees with fused relative rotation by 13° after frame 930, so none is accepted as a pose-quality fix.
- Active /root/terra_sample_quality: prepare all 138 reviewed timestamps as 276 physical-lens observations with no feature holdout, paginated operator-mask review sheets, fixed rig hypotheses and quaternion provenance. Root must review masks before the broader SfM run.
- /root/terra_export_baseline: completed the 138-timestamp export, verified both packet streams within 1 μs and exact image hashes for the prior 16-frame subset. Output 472 MB; free disk 39.7 GB, above the 35 GiB reserve.
- Viewer remains on port 5178. Its direct state catalog selects a run profile; the retired legacy publisher is stopped. Native geometry completion and workflow activity are separate. The live profile shows “Camera reconstruction — Testing orientation constraints,” verified through /api/state and browser. No overall reconstruction-complete claim is justified.
