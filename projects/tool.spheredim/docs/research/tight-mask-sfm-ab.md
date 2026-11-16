# Reviewed tighter-mask native 360° SfM comparison

This is an experiment on one recording, not proof of camera or 3D accuracy. It compares two operator masks on the same 138 timestamps, sampled every 15 frames from 0 to 2055 (<69 seconds), at 1024×512 equirectangular resolution. No perspective views or cubemaps were created. The first comparison accidentally moved the synthetic black edge out to the feature-mask boundary; that run is invalid. The results below are from the corrected `-v2` workspaces.

The input is the same horizon-stabilized, yaw-preserving, rolling-shutter-off image in each arm. Before feature extraction, pixels in each arm's exclusion region were set to black; only the exclusion masks differ. White-keep feature masks additionally exclude 32 pixels around the blackout boundary, with horizontal seam wrapping. This means pixel content changes with the mask, not just the binary SfM mask. Source images/masks are private recording derivatives and do not belong in the repository.

The tighter masks were visually reviewed at reduced display resolution at these 138 sampled times; no conspicuous large missed operator region was observed. Small leaks and false positives are possible, and no intervening frames or the final three seconds were reviewed. Before the extra feature guard, the broad exclusion covers a median 35.35% of spherical solid angle; the tight exclusion covers 11.62%. Feature guards increase excluded medians to 44.04% and 18.19% respectively.

| Metric | Broad | Tighter reviewed mask |
| --- | ---: | ---: |
| Images and masks | 138 / 138 | 138 / 138 |
| Retained SIFT features | 106,119 | 191,300 |
| Verified matched pairs | 1,145 / 2,487 | 1,873 / 2,344 |
| Inlier correspondences | 60,348 | 131,372 |
| Distinct registered images | 124 / 138 in two components | 134 / 138 in one component |
| First-component points | 5,060 | 22,774 |
| Mean reprojection error, first component | 0.484 px / 7,228 observations | 0.502 px / 30,621 observations |

Reprojection errors reflect different observation sets and cannot establish absolute accuracy or prove a 1% target. Extraction/matching/mapping took 3.44/26.58/4.51 s for the broad arm and 4.49/48.66/8.75 s for the tight arm; GPU contention and different feature counts mean this is not a controlled speed benchmark.

Spirula's SIFT path extracts descriptors first, then filters their centers using the mask. Because excluded source pixels are blacked before extraction, an accurately masked operator is not present in the extractor's input; a feature can still have descriptor support crossing the artificial black edge. The fixed 32-pixel feature guard does not eliminate this for large SIFT scales: an estimated 3.32% of retained broad-arm and 1.65% of tight-arm descriptor windows intersect the blackout region. This estimate uses the shader's approximately 10.61× keypoint-scale square support; pyramid blur can extend farther. A scale-aware support filter would be a more robust fix.

The tight model's 134 registered cameras span 0–68.5685 s; sampled frames 1200, 1305, 1500 and 1560 did not register. A speed-outlier check flags the camera at frame 1785 (59.5595 s): SfM rotates 39.6° and 27.2° across adjacent half-second transitions, while DVO and fused sensor heading indicate roughly 6–10°. The sensor and DVO are estimates, not ground truth. The original model retains this camera. The separate splat-pose experiment explicitly excludes it and records the exclusion.

After a single global similarity alignment to the same-footage 360DVO trajectory, the tight SfM camera positions differ by 0.87% RMS and 1.81% p95 of the compared DVO path length; orientation disagreement is 5.41° median and 12.49° p95. These numbers compare two correlated estimators and do not measure true error.

Reproduction: generate matched frames/masks with `prepare.py` using `--guard 32`, run `run-v2.py`, and inspect `sfm-broad-v2.log`, `sfm-tight-v2.log`, `feature_support.py`, and `trajectory-audit.json`. The SfM command for each arm is identical:

```sh
spirula sfm auto "$IMAGES" -o "$WORKSPACE" --camera-model equirectangular --camera-mode single \
  --masks "$MASKS" --data-type video --quality medium --max-image-size 1024 \
  --features sift --matcher bruteforce --pairs sequential --sequence . --overlap 10 \
  --threads 4 --decode-threads 2 --progress-dir "$PROGRESS"
```

The temporary workspaces are under `/private/tmp/spheredim-tightmask-ab`; preserve the real recording, masks, feature caches, and model data outside source control.
