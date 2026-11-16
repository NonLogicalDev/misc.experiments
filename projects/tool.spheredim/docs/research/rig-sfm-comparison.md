# Physical two-lens SfM comparison

The computed lens separation has been tested in native spherical GPU SfM. It does not yet provide a reliable quality improvement: the metadata-derived rig has a slightly lower median held-out error, a higher 90th-percentile error, and a clearly suspect pose at source frame 930. Do not promote these poses as a quality fix or use them to justify another long splat run.

## Controlled inputs

The test uses sixteen synchronized timestamps, frames 840–1065 at 15-frame intervals, approximately 28.03–35.54 seconds. Each timestamp has two actual physical lens observations projected separately into nominal body-oriented full equirectangular images at 1024×512. No virtual perspective or cubemap views are extracted. Original lens calibration is already applied during projection; the rig uses only the separately fitted residual rotation, not the embedded lens orientation twice.

Reviewed operator masks are inverse-mapped from horizon-leveled coordinates into the unstabilized body images. Source support, operator keep, feature guard, and held-out feature masks remain separate. The controlled runs use byte-identical images, masks, all 32 feature files, and matches. The two image cameras share one body pose per timestamp and fixed relative extrinsics. The global mapper is used because the pinned incremental mapper initially drops supplied nonzero rig translations.

Spirula Studio v2026.11.12, commit `667e353bca3941303a4d93e93aa8ae3f2c202712`, ran on Apple M2 Pro through Vulkan/Metal with float bundle adjustment. Each arm took approximately eight seconds. Private artifacts are under `/Users/nonlogical/Downloads/SphereDim-VID_20181001_170023_00_104/`; the scripts record hashes and commands.

## Baseline hypotheses

The encoded translation is `[0.000191, -0.000054, -0.031857]`, with norm `0.031857618335337`. If the units are metres, this is 31.8576 mm. Units and reference-frame semantics are unconfirmed. The metadata hypothesis treats that difference as the second lens center in lens0 axes, maps it through the inverse lens0 orientation, and then converts to the SfM camera basis. Its direction differs from the image-fitted direction by 0.5392 degrees. The same fitted residual rotation is retained in all arms.

The user's approximate 25 mm lens-base measurement and teardown showing folded optics do not establish the optical baseline. Sensor placement, lens bases, and effective viewpoints are different reference points. The physical test must therefore retain the units assumption rather than claim a measured 31.86 mm baseline.

| Run | Fixed baseline magnitude | Registered timestamps | Median common error | 90th percentile |
| --- | ---: | ---: | ---: | ---: |
| Shared center | 0 | 16/16 | 0.577 px | 1.506 px |
| Fitted direction, unit length | 1 | 15/16 | 0.590 px | 1.644 px |
| Fitted direction, metadata length | 0.0318576183 | 16/16 | 0.555 px | 1.783 px |
| Metadata direction and length | 0.0318576183 | 16/16 | 0.538 px | 1.716 px |

These are angular errors expressed in equivalent equirectangular pixels at width 1024. The comparison uses the same 80 tracks and 95 intermediate observations, triangulating their identical common endpoints. It necessarily excludes frame 930 because the unit-baseline arm did not register it. Raw coverage, failed triangulations, and observations remain in the report; they are not silently dropped. Changing baseline length alone should change scene scale in ideal geometry, but this implementation changed registration at frame 930 when the numerical scale changed. That sensitivity needs investigation.

## Failure inspection

The shared-center model's rotations around frame 930 disagree with fused camera orientation by 20.02 and 42.58 degrees. The corresponding disagreements are 21.03/40.04 degrees with fitted direction at metadata length and 25.70/41.02 degrees with metadata direction and length. Neighboring intervals in the shared-center model disagree by approximately 0.41–1.22 degrees. DVO independently shows the same abrupt failure, although neither DVO nor fused orientation is ground-truth trajectory. Registering the timestamp does not establish a correct pose.

The largest common residual is a false feature track joining opposite corners of the same artwork. It remains in the reported comparison. Two large residuals involving frame 930 follow recognizable artwork features, supporting a pose failure; repetitive wood-grain matches remain ambiguous. Pairwise essential-matrix verification alone did not remove every false correspondence.

## Evaluation protocol and limits

An initial grid split overwhelmingly sampled one lens and included obvious false matches. Preserve its raw results, but do not use them to claim improvement. The replacement split reserves one 256×256 block per lens and was chosen before observing its reconstructed poses. Source-only spherical essential RANSAC rejects inconsistent pair matches; its refit now cannot replace a larger consensus with a smaller one. The corrected protocol yields 92 candidate tracks. Feature locations are withheld, but this is not complete RGB independence: training descriptor footprints can sample nearby content.

None of the retained tracks links both lenses, so the common comparison tests temporal reprojection within each lens, not direct cross-lens accuracy. The fitted calibration also comes from this recording. No metric ground-truth trajectory or final splat-quality improvement is established by this experiment.

## Native telemetry follow-up

A fifth run attaches the original INSV through the supported `--telemetry` option with `--sensor-gauge up --metric-gps none`. The stock backend cannot load the existing fused quaternion CSV directly. Its matching/mapping logs reject sensor calibration for both camera groups because only 8 and 16 suitable pairs remain, below its minimum. A later orientation pass still levels and rescales the model by 0.6945, changing its output baseline from 0.031857618 to 0.02212605. The native-telemetry arm has 0.580 px median and 1.900 px 90th-percentile error on the same 95 common observations; the bad pose remains. Image and match records are byte-identical to the other arms; the match file hash differs because a telemetry calibration-sample section is appended. Therefore loading telemetry must not be reported as successful gyro-constrained reconstruction, and final output scale must be checked separately from configured rig scale.

## Explicit orientation constraints

Pinned layerctl layers now accept camera-to-world quaternion CSV priors, preserve fixed rig scale, and perform a final joint solve after late registration. The first experimental version also affected hard seed/PnP gates; its outputs are retained but should not be treated as a pure soft-prior comparison. Version 2 removes those gates. Version 3 includes all 32 images, 16 body frames and 15 relative factors in its final bundle adjustment, with zero free rig parameters. The compiled binary SHA-256 is e4005229cb294e3860c62968e87a9818044c1a70e89f4401677a0b76234f8196.

On the 82 tracks and 106 residuals valid in all four version-3 runs:

| Run | Median | 90th percentile | 930–945 orientation disagreement |
| --- | ---: | ---: | ---: |
| No explicit priors | 1.018 px | 30.326 px | 40.03° |
| Per-image σ = 1° | 1.103 px | 4.100 px | 27.40° |
| Per-image σ = 0.5° | 0.943 px | 6.118 px | 14.37° |
| Per-image σ = 0.25° | 0.857 px | 3.298 px | 13.00° |

All four runs have identical feature and match files and retain the fixed baseline. The control has ten tracks with failed positive-depth triangulation; prior arms have none. All raw results and exclusions are preserved in sensitivity-audit.json. These prior-strength trials reuse the benchmark and are tuning diagnostics, not independent validation. Improvement is not monotonic across every metric, and the failure after frame 930 persists.

At actual rig poses, central finite differences matched the host residual Jacobian and robust cost gradient within 4e-9 relative error. The CSV rotation convention reproduces the independent fused-orientation calculation. This does not verify the Vulkan solve. The prior uses Huber loss, so a large disagreement receives a low iterative weight; competing visual residuals and initialization remain plausible causes.

A same-input CPU-BA run retained 19.62° disagreement over 930–945, versus 27.40° on GPU. On their common 92 tracks and 126 residuals, CPU median/p90 errors were 1.041/4.106 px versus GPU 1.195/5.410 px. These figures use a different common set than the four-arm table. Identical executable, dataset, rig, CSV, feature and match hashes isolate the requested BA backend choice, but the result does not establish solver parity or identify the source of the difference.

## Larger reviewed reconstruction

A broader run uses all 138 reviewed timestamps from source frames 0–2055 in steps of 15, covering 0–68.5685 seconds. Both physical lens streams have verified source packet timestamps within one microsecond; the overlapping 16-frame subset reproduces the original exported image hashes. Operator masks are transformed into body coordinates as before. Root inspected all 18 contact sheets. Production preparation uses all guarded feature locations and no held-out feature region.

The Apple GPU run with metadata baseline and the original 1° per-image prior assumption took 59.9 seconds, registered all 276 images in one model, and produced 24,614 sparse points. Its final solve included 138 body frames and all 137 relative prior factors. Training reprojection mean/median is .468/.341 px; these are training residuals, not independent accuracy. Motion consistency and subsequent image reconstruction remain to be checked. The live viewer exposes this model separately from the earlier 16-frame sample and splat.

## Evidence

- `rig-dataset-20261115-balanced/manifest.json`: image and mask provenance.
- `rig-dataset-20261115-balanced/rig-baseline-provenance.json`: encoded separation, coordinate assumptions, and configuration hashes.
- `rig-comparison-20261115-balanced/heldout-comparison-v2.json`: corrected zero/unit comparison.
- `rig-comparison-20261115-metadata/manifest.json`: commands, executable hash, and input hashes.
- `rig-comparison-20261115-metadata/four-model-audit-verified.json`: identical-observation comparison and fused-orientation checks.
- `rig-comparison-20261115-metadata-imu/metadata/run.log`: sensor-calibration rejection and final orientation behavior.

Reproduce with the tools documented in [native spherical reconstruction](../../tools/native-sfm/README.md), using uv and the external runtime. No private recording or binary artifact belongs in Git.
