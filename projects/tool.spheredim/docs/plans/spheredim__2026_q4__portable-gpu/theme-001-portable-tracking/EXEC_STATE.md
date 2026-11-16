# Portable GPU tracking

- Status: active; Apple GPU prototype installed and image-accuracy target not yet met.
- Goal: run 360DVO on Apple and AMD GPUs without its CUDA-only extensions and retain spherical input and usable poses.
- Next action: investigate low-texture failure and image alignment, add confidence/failure reporting and seam/long-video tests, and validate and package AMD ROCm on suitable hardware.
- [Plan](active/plan-01%20Portable%20360DVO.md) · [Owners](../OWNERS.md)

## Current execution: quality and runtime optimization

- Active `/root`: integrate finer physical-rig splats and lower runtime. Dense 6k remains the fixed 50% pooled-error target anchor; Native SfM 2048 / 7k is the current numerical incumbent (2.27% below the original 7k). Fine texture and equal-work runtime targets remain unmet.
- Completed `/root/astra_paper`: revised 13-page Typst report around accurate and fast hardware-accelerated reconstruction from ordinary single-device 360 footage, beginning with stitched panoramas. Includes operator masks, physical-lens alternatives, Apple/AMD kernel work, diagrams and measured comparisons. All pages visually reviewed; numerical/source verification passed. Private figures/PDF stay outside upstream commits.
- Completed `/root/trainer_profile`: controlled source-edge allocation trial took 1,018.02 s and exported 927,928 splats. Native-2048 spherical error is 1.67% above its fresh control; fixed-1024 error is 0.27% above dense 6k and 8.58% above dense 7k. No quality promotion. Matched crops still lack blind slats and clock markings.
- Completed `/root/frame_plan`: candidate published through state with its original 412-position path; prior selection preserved. Viewer remains running on LAN port 5178.
- Completed `/root/detail_diagnostic`: native temporal depth pilot found nine provisional matches among 68 patches, mostly near the window border/foliage; no seed points generated. Eight focused tests passed, including rotated-camera known-depth recovery and duplicate-observation rejection.
- Completed `/root/trainer_profile`: one-view geometry fitting recovered visible slats, but the nine-view follow-up generalized inconsistently: frame 1500 improved 50.2%, held-out 1560 improved 13.9%, held-out 1440 worsened 82.0%. No diagnostic is promoted. The original 7k model remains intact; generated diagnostic checkpoint payloads have retirement ledgers, while renders, configs and comparisons remain.
- Completed `/root/trainer_profile`: native SfM 2048 / 7k completed in 818.62 seconds; fixed-1024 spherical error 0.00348914 is 2.27% below original 7k and 9.75% below fixed 6k. Native-2048 spherical error is 0.00382459, 2.92% below original 7k at that resolution. Export has 293,942 splats. All 36 comparison identities and source reductions verified. Fine detail remains insufficient. Candidate published, selection preserved.
- Completed `/root/detail_diagnostic`: signed native bearing audit found small coherent spatial residuals, with median magnitudes 0.235/0.222 ERP1024-equivalent pixels. Camera, mask and track provenance verified; four focused tests pass. No calibration change justified by this in-sample evidence.
- Completed `/root/trainer_profile`: zero-update 3DGUT swap did not recover detail and slightly increased error at three views. Its 10.69 MB output exceeded the planned 8 MB limit; aggregate storage remained below 15 GB. Duplicate references were hardlinked afterward, and the private monitor now checks limits after process exit.
- Active `/root/trainer_profile`: preserved original 7k full-state continuation to 15k, same 788/36 split and 300k population. Resumed step 7000, config and scene transform checked. Refinement remains stopped at 4000, terminal learning rates unchanged, original exponential noise function extrapolated without restarting it. View sampler may restart its sequence; this is additional exposure, not a bitwise uninterrupted run. Final compact output budget 180 MB, timeout 1500 seconds, with all storage guards.
- Active `/root/frame_plan`: actual additional-update progress and separate finished candidate through state, preserving selection. Two obsolete broad-mask previews retired with hashes and decoded samples, reclaiming 267.31 MB; original footage, clean reference and all PLYs/checkpoints remain. All 20 scene states and 39 available artifact endpoints checked. Active `/root`: compare results and integrate. The fidelity target remains unmet.

- Completed selection controls: fresh adaptive SfM produced a path jump and 3.34× dense-6k spherical error. Keeping original geometry/seed recovered most of it but retained soft detail. Replacing twelve frames while retaining full coverage completed in 377.94 s; spherical error is 3.52% above dense 6k and 12.10% above dense 7k. Matching crops still lack blind slats/clock markings; all candidates remain selectable without quality promotion.
- Completed native 2× preparation: 412 timestamps / 824 physical-lens observations at 2048×1024, about 1.03 GB unique output. Ordered names, poses, splits and doubled ERP metadata verified. All 36 held-out references downsample exactly to prior RGB on common valid pixels. Zero-step validation completed; 100 training updates regressed held-out error 2.49%, so no candidate is promoted.
- Completed periodic renderer integration: full RGB build and registry check passed. Zero-step same-checkpoint seam repair lowered held-out overall error 0.19% but raised selected training-view error 0.69%; not promoted. Meshing/moments and AMD remain unverified.
- Completed `/root/frame_plan`: repaired clipboard copying, reconstruction switching and stale saved scene choices, and added state-driven restoration of copied camera views. Unit tests and build passed; live verification loaded native-2048 sparse geometry and 8k/10k splats. Viewer remains available on localhost and direct LAN port 5178.
- Dense SfM: 824/824 observations registered in 108.33 s, 74,984 points. Explicit-pair baseline has 24,611 points in 61.86 s; the separate original reviewed baseline has 24,614. More points are not independent pose accuracy.
- Dense 6k took 378.42 s including evaluation; against older rig10k, spherical error fell33.49%. Continuing6k→7k lowered the same36-view error another7.65% and selected10 training captures4.12%, without convincing fabric/blind detail recovery. All good checkpoints remain preserved.
- Verified pushed checkpoints: `951995046b8f4a2d20c6563604b4a0d3362338c6` records native geometry/detail diagnostics; `232d56fdf7baaf59381649cf7ddb1e8e8d307c53` repairs viewer scene selection and copying. Fixed-window selector checkpoint `b826f7c` is also verified pushed. Unrelated SolidRecipe changes remain untouched.
- Next: test reliable multi-view surface support and determine a discriminating local-view diagnostic before another full training run. More capacity, sharper frame replacement, and edge allocation have not recovered fine detail. Keep the fixed 6k acceptance anchor and 7k numerical incumbent.
- Evidence: [living quality report](../../../research/reconstruction-quality-report.md), [quality plan](active/plan-04%20Reconstruction%20quality%20implementation.md), [high-resolution preparation](active/high-resolution-pilot-support.md). Older entries below are history.

## Prior execution: larger physical-lens reconstruction

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

## Adaptive selection reconstruction budget

The operator requested a processed preview of the selection. At launch preparation, measured task storage is 14.386 GB and support is 1.955 GB. Five inactive diagnostic optimizer states were losslessly compressed with decompression SHA verification and restoration records; all displayed PLYs and good baseline states remain available. Archive records are under `/private/tmp/spheredim-storage-prune-20261116/`. Limit the new trial to 500 MB additional storage with a 15 GB aggregate cap and 35 GiB free reserve. Use hardlinks for existing input images/masks and save only the final splat checkpoint. No new native exports or build are needed.

## Adaptive processed result

All 580 lens images registered into one 56,620-point model. The corrected SfM retry took 47.87 seconds but reused work from an earlier CSV-header failure, so no clean speedup is claimed. The 6k splat completed in 345.43 seconds. Fixed 36-view spherical/raw MSE ratios are 3.3396/2.9399 versus dense 6k and 3.6163/3.2138 versus dense 7k. It is visible as `Adaptive frames · 6,000-step splat` in the viewer; default selection is for inspection, not quality promotion. Largest errors include frames 720/840. Camera-solution diagnosis remains active. Final measured storage is about 14.745 GB total and 1.955 GB support; all original footage and good checkpoints remain preserved. Selector checkpoint 36f8a30 and fixed-split helper checkpoint ce87882 are verified pushed.

The operator confirmed visible regression. Active `/root/trainer_profile` now isolates frame selection with a 6k run using the original dense camera poses and complete initial point cloud. Keep the same selected training timestamps, original 36 evaluation images and reviewed masks. Use a compact final checkpoint and a 180 MB total trial budget; do not rerun SfM or change source pixels. `/root/detail_diagnostic` reviews subset preparation; `/root/frame_plan` publishes the separate result and its own progress.

Active `/root/detail_diagnostic`: audit original landmark observation coverage under the reviewed training masks and design coverage-first selection favoring sharp observations. Preserve the dense SfM path as the backbone. Include temporal overlap between selected frames, distinguish simultaneous stereo from separate timestamps, and report featureless surfaces as unknown. The fresh adaptive path contains a verified 860→870 translation outlier; the viewer displays the correct ordered source geometry.

## Current continuation: sharper source observations

The fixed-pose control completed: 366.65 seconds, 296,396 Gaussians, spherical MSE 0.00380554 (1.56% below dense 6k, 6.60% above the 7k incumbent), with visible detail still soft. It is the viewer default for inspection and keeps the established 412-pose track. No quality promotion and no twofold improvement are claimed.

Completed `/root/detail_diagnostic`: masked landmark coverage audit and conservative constraint feasibility probe; six focused tests passed at root. The previous selection loses two-view support for 15,747 landmarks. The three-view-per-track probe retains all 394 original training timestamps and is not a production selector. Completed trainer source audit shows calibration correction warps per-image reference pixels rather than optimizing a rigid camera pose; it stays disabled.

Active `/root/trainer_profile`: implement and test a bounded four-worker source scan using the unchanged original exporter. The old 20-candidate pilot spawned 16 native workers. Preserve exact paired PTS and pixels, common-window masks and scores, and bounded temporary storage; measure parity and timing before wider scanning. Do not start a native build until its support budget is measured. `/root` is losslessly archiving inactive temporary source/build artifacts and restoring the verified original runtime within the storage cap. The goal remains half the dense 6k image error plus convincing fine-detail recovery at matching viewpoints; frame-count reduction alone is not a success.
