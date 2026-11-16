# Native spherical reconstruction

`prepare.py` and `run_sfm.py` prepare and reconstruct a full equirectangular video. The rig experiment instead keeps the two physical lens observations separate, with one rigid body pose per synchronized timestamp. It never extracts perspective views or cube faces.

## Paired rig experiment

Use `prepare_rig.py` with a manifest produced by `scripts/export_overlap_probes.py`, reviewed operator masks, the matching fused orientation CSV and a fitted rig report. Run `--help` for the positional arguments. Outputs include image validity, separate feature guards, held-out feature regions, mask review sheets and two rig configurations. Inspect operator coverage in both lenses before reconstruction.

The source images are already projected into nominal body-oriented ERP axes. Do not apply the embedded physical lens rotations a second time. The fitted residual lens rotation is converted into the SfM ERP basis, and camera-center separation becomes a camera-from-rig translation. The supplied unit baseline does not claim metric calibration. The tests include a known landmark to check this convention.

`run_rig_pair.py BINARY DATASET NEW_OUTPUT` runs the exact same images, masks and options twice: fixed relative lens rotation with zero separation, then with the fitted unit baseline. It uses the global mapper because the pinned backend's incremental mapper initially drops supplied nonzero translations. Bundle adjustment defaults to GPU float precision on Apple; `--ba-real cpu` selects the host reference for both normal and coarse solves. Supported values are `float`, `double`, `df`, and `cpu`; the runner records the choice in its manifest. The runner enforces a 35 GiB free-space reserve, 512 MiB output budget and a per-run timeout. `--status FILE` publishes progress for a generic viewer state producer and ends when camera pose estimation finishes; it does not run held-out evaluation.

`compare_rigs.py` extracts tracks from feature locations withheld from the SfM runs. It triangulates the first and last observation and predicts intermediate observations, using the same observations for the shared comparison. It reports angular error in equivalent ERP pixels, coverage, failed triangulations and whether the output obeys the rig constraint. Feature locations are withheld; training descriptor footprints can still sample nearby image content. These are real-image consistency measurements, not ground-truth trajectory accuracy. The evaluator accepts COLMAP text or binary image poses.

Run Python through an external uv environment, for example from the project root:

```sh
uv run --isolated --no-project --python 3.14 \
  --with-requirements vendor/360DVO/requirements-macos-arm64-py314.lock \
  python -m unittest discover -s tools/native-sfm -p 'test_*rig*.py' -v
```

The same environment runs the preparation and evaluation commands. The runner itself uses only the Python standard library. Input recordings and generated datasets/models belong outside Git; their manifests record source hashes and exact settings.

## Encoded lens separation and telemetry

`prepare_rig_baselines.py --calibration FILE --rig FILE --fit FILE --output-dir DATASET` writes two additional fixed-rig hypotheses and a provenance record. `fitted-metric` scales the image-fitted unit direction by the metadata translation magnitude; `metadata` also uses the metadata-derived direction. The conversion treats the raw translation difference as a lens center in lens0 axes and maps it through the inverse lens0 orientation. Those metadata semantics and units remain assumptions. The helper preserves the existing source images and rig rotation and refuses to overwrite outputs.

Use `run_rig_pair.py BINARY DATASET NEW_OUTPUT --arms fitted-metric metadata` to compare them. The runner verifies that only cam1 translation changes across supplied configurations. `audit_rig_models.py` compares saved held-out tracks with identical observations and endpoints across multiple runs, retains raw coverage and failures, and checks relative rotations against the supplied fused orientation CSV.

The optional `--telemetry ORIGINAL_VIDEO` attaches the original recording using the backend's stock gyro and accelerometer support. This is not a rotation-only experiment: accelerometer factors can enter bundle adjustment, and final sensor orientation can rescale the output even with a fixed rig baseline and `--no-orient`. Inspect calibration acceptance, actual prior counts, and output baseline before attributing any result to IMU constraints. The backend needs enough suitable visual pairs to calibrate the sensor-to-camera transform; merely loading the recording does not prove that priors were used.

### Preparing a physical-lens splat experiment

`prepare_splat.py DATASET MODEL TRAINER OUTPUT --run-name NAME` prepares a reviewable command and dataset without training. DATASET is a completed `prepare_rig.py` dataset; MODEL is its native COLMAP model directory. It validates source image and mask hashes, hardlinks each paired native ERP observation and keep mask, preserves the model's per-image camera transforms, and writes its colored points as a seed PLY. The recording's prepared observations are 1024×512; no additional image resampling occurs here. White masks mean keep, and the source images have already been blacked outside physical support and the reviewed operator exclusion.

The pinned trainer's filename split identifies `train` and `eval` in image basenames. Every eighth timestamp is held out for both lenses; the manifest records each source frame, lens, packet timestamps, and the held-out output ordering. The seed and camera poses were estimated using these observations, so this tests novel splat training views rather than independent SfM. The manifest records a short command and resource limits, but does not enforce those limits. Use the guarded runner for a controlled held-out diagnostic. Path-point quality acceptance additionally requires rendering original training cameras with their original per-camera appearance state; changing the evaluation split is not equivalent. Existing ERP seam and mask-boundary limitations still apply.


`run_splat.py MANIFEST STATUS LOG --activity-state ACTIVITY` verifies the prepared inputs and exact training options, then runs the GPU trainer with a 35 GiB free-space reserve, a 1 GiB output cap, and a timeout. `--iterations` and `--save-every` belong to preparation; `--timeout` belongs to the runner. It rejects split camera projections and publishes only complete, stable binary splat PLYs. Training completion leaves image comparison pending. The optional activity JSON drives the viewer without editing viewer source.

`evaluate_splat.py MANIFEST RUN REPORT CONTACT_SHEET --doorway-frame FRAME` checks the saved reference pixels and masks against the prepared dataset before scoring the held-out renders. Use `--compare-to PREVIOUS_REPORT --baseline-label LABEL --label LABEL` for an identical-view comparison. Reports include spherical area-weighted PSNR, masked-window SSIM, gradient contrast, and per-view results. No image alignment or filtering is applied. These measurements do not establish trajectory ground truth or replace visual review.

The rig runner defaults to exhaustive matching. `--pair-mode sequential` is an experimental alternative that matches per-folder temporal neighbors plus content-based retrieval. It does not guarantee cross-lens matches, and retrieval still scores all image pairs. Compare graph connectivity, registration and pose quality against exhaustive matching on the same reviewed inputs before using it for a larger run. The chosen mode and complete command are recorded in the run manifest.

### Preparing a denser controlled rig experiment

`prepare_dense_rig.py BASELINE CANDIDATES SOURCE FIT NATIVE EXPORT_RUNNER FUSED OUTPUT` validates the existing physical-lens baseline, visually inspected candidate-mask manifest and sheet hashes, raw INSV, pinned exporter extension and fitted rig. Without `--execute` it prints a plan and launches no export. The `--execute --seek` path exports only added timestamps in bounded batches, checks every paired exporter timestamp and both source-stream packet PTS, prepares the same 2048-to-1024 area downsample and all-subpixel support rule as `prepare_rig.py`, and hardlinks unchanged baseline samples. `--pilot --batch-size 2` prepares only the first two added timestamps to check the workflow. The dataset retains the baseline rig metadata and generates one-degree rotation priors, checking every baseline prior row and full image coverage before completion. The outputs are a controlled reconstruction experiment: propagated operator candidates are not pixel-level truth. Review every new per-lens overlay before reconstruction.

The guarded runner writes `status.json` with batch, timestamp count, elapsed time, incremental output and free bytes. It enforces a 400 MiB incremental cap, a 35 GiB free-space reserve and a per-batch timeout; its temporary 2048 files are removed only after derived masks, images and source hashes have been recorded. Source and prepared batch manifests and per-lens review sheets remain in `provenance/` and `review-new/`. Original reviewed keys and the baseline dataset are not modified. GPU export runs four physical-lens image/support passes per batch; coordinate a GPU window before `--execute`. The fitted rig, orientation stream and original baseline options are preserved for a controlled comparison, not treated as ground truth.

Timestamp seeking was checked at source frames 840 and 855 against the baseline index export: both emitted PTS and all eight lens/support hashes matched. This validates those tested frames only; the integrated workflow checks every requested timestamp but its newly exported pixels do not have an independent index-export hash unless separately tested.

### Sharp-frame selection

`select_sharp_frames.py SOURCE REVIEW_MANIFEST FUSED_CSV NEW_OUTPUT --targets FRAME... --radius 2` evaluates synchronized lens pairs near each requested source frame. Run it in the same Python environment and `PYTHONPATH` used for `export_timestamp_probes.py`, with OpenCV, NumPy and SciPy available. It exports up to eight 1024×512 candidates at a time into a temporary directory, removes each batch after reading, and records candidate scores, source PTS, mask and input hashes in `selection.json`. Windows are clipped at target midpoints; ties choose the candidate closest to the target, then the earlier frame. Each score uses the weaker lens and the median of tiles textured in at least one candidate, using pixels valid in every candidate in its window, after smoothing, downsampling, a noise floor and bounded edge contributions.

The score mask intersects physical lens support with the union of exclusions from the nearest bracketing reviewed stable masks, transformed using the candidate's fused orientation. This is a propagated scoring mask, not a newly reviewed operator mask. A high score does not guarantee the absence of motion blur or noise. Generate and review masks at the selected actual timestamps and run fresh pose estimation before reconstruction; do not reuse previous poses for a different selection. The selector fails when it cannot verify a matched lens pair, mask brackets or sufficient textured coverage. It monitors temporary output against 40 MiB and a 35 GiB free-space reserve every 250 ms; a fast writer can temporarily exceed the limit. The final report and evidence are checked against 5 MiB. This does not enforce aggregate task or support storage budgets.

To export the selected full-resolution observations, first verify that the source SHA-256 matches `selection.json`. Pass its ordered `selected_indices` and `selected_timestamps_microseconds` (divide timestamps by 1,000,000 for decimal seconds) as `--indices` and `--timestamps` to `export_timestamp_probes.py --source SOURCE --output NEW_OUTPUT --width 2048 --seek-early-us 1`. The exporter checks the paired output timestamps; verify packet PTS and prepare reviewed masks and fused orientation for these selected frames before running `prepare_rig.py` and fresh SfM. The selector also writes a 512×256-per-image requested/selected evidence sheet for the first four targets.

Frame indices come from the fused CSV; packet checks verify matching physical-stream timestamps, not independent decoded frame-index identity. Camera motion can change the scene within a tile, so scores cannot attribute a difference solely to blur. Early seek changes the query by one microsecond but the exporter still rejects any actual output timestamp other than the requested target.

`select_adaptive_frames.py DATASET VIEWER_POSES NEW_REPORT --window 6 --timeout 300` is a CPU prototype over the existing paired 1024×512 ERP dataset. It scans from the last accepted frame, measures matched bearing change after fused and rig rotation compensation, and ranks candidates with a bounded age penalty after an overlap and measurable-texture gate, with local relative sharpness as a soft ranking factor. Try `--window 2` or `--window 3` for sensitivity. By default it scans all manifest frames; `--limit` bounds the input prefix and must be at least two. A low match count or textureless lens is reported as unknown. The selector stops incomplete if the maximum gap contains no candidate with measurable texture and sufficient overlap; do not treat a partial selection as a complete dataset. Its selected indices and timestamps feed the existing timestamp exporter after verifying source identity. The preliminary pose file supplies post-hoc position coverage only, and its SfM used orientation priors. Coordinate convention, exposure normalization, moving scene content and relative sharpness are limitations; no feature score establishes physical surface coverage or proves blur.

To keep a comparison fixed when selecting fewer frames, pass `prepare_splat.py --eval-frames-json FRAMES.json` with the original evaluation source indices. Both physical lenses at those timestamps remain evaluation images. Include those timestamps in the SfM inputs even if the selector omitted them; exclude them from training. `--compact-final-checkpoint` omits optimizer state and requires `--save-every` to equal `--iterations`; the default retains the full checkpoint. Saving only at the final iteration reduces disk use without changing the training schedule.

`audit_landmark_coverage.py MODEL PREPARED SELECTION NEW_OUTPUT_DIR` compares retained original SfM landmark observations against the full training set, using the prepared dense training masks and excluding the held-out timestamps. It writes aggregate JSON and compressed per-landmark counts, baselines and view-angle spreads. Stereo observations at one timestamp do not count as separate temporal views. These are reconstructed features and approximate poses; they do not measure unobserved or featureless surfaces.

`select_track_coverage.py MODEL PREPARED SELECTION NEW_REPORT [--compare-cap 272]` is a CPU feasibility prototype. It starts with every original training timestamp, removes lower-ranked matched-patch observations only when original ≥3-timestamp tracks retain three timestamps and at least 80% of original baseline and angle, and checks adjacent selections for 20 shared tracks. The thresholds are experimental, not verified reconstruction requirements. A cap is an optional comparison, not a forced output size. Patch gradients are relative proxies confounded by viewpoint, scale, exposure and texture. Source and mask hashes are checked; fixed held-outs are excluded. Review the report and actual image detail before using the selected timestamps; this does not estimate new poses or demonstrate visual improvement.


### Sharper replacements with the original camera path

`select_sharp_stream.py SOURCE REVIEW_MANIFEST FUSED_CSV NEW_OUTPUT --targets FRAME... --radius 2` runs the same native candidate scorer with four persistent physical-lens image/support exporters. It verifies exact paired timestamps and input hashes, pauses exporters while consuming a window, and bounds its spool and report size. The original exporter remains unchanged. Use the pinned UV dependencies and original exporter extension through `PYTHONPATH`; the generated plan records their identities. This helper does not enforce the aggregate task-storage budget.

`prepare_sharp_replacements.py NATIVE_MANIFEST MASK_MANIFEST SELECTION_REPORT BASELINE NEW_OUTPUT` prepares the current thirteen-pair diagnostic from native 2048 images using the dense baseline's area reduction and mask rules. It requires the unchanged frame-1350 control and verifies selection and operator-mask provenance. This is an experiment-specific helper, not a general dataset exporter. A separate watchdog must enforce the combined export/preparation budget.

`register_rig_frames.py --help` lists the model, original workspace, new feature-cache and source-manifest inputs for local physical-rig registration. It recovers original landmark descriptors from verified native feature/match indices, fits one body pose per actual selected timestamp, and checks both lenses and spatial support. It leaves the original model and seed unchanged. See [registration notes](registration-notes.md) for conventions, controls and acceptance limits.

`prepare_sharp_overlay.py BASE_MANIFEST REPLACEMENTS REGISTRATION NEW_OUTPUT --run-name NAME` creates the current twelve-replacement training comparison. It preserves all other original camera rows, all evaluation inputs and the original seed through hardlinks, with no stale feature associations in its text model. The helper's `verify` function reconstructs expected inputs before a guarded launch; it does not itself start training or enforce output budgets. The preparation and verifier share code, so independent pose-composition tests remain necessary. Do not use the ordinary `run_splat.verify` for this overlay: its source-model check intentionally expects an unmodified dataset.

Focused checks run from this directory with the existing external UV dependencies:

```sh
uv run --offline --isolated --no-project --python 3.14 \
  --with-requirements ../../vendor/360DVO/requirements-macos-arm64-py314.lock \
  python -B -m unittest test_stream_sharp_frames test_select_sharp_stream \
  test_prepare_sharp_replacements test_recover_landmark_descriptors \
  test_rig_pose test_register_rig_frames test_prepare_sharp_overlay \
  test_audit_landmark_coverage test_select_track_coverage
```


`targeted_geometry_tracks.py BASELINE_MODEL NATIVE_MODEL PREPARED NEW_REPORT` compares two camera solutions using frozen original 1024 source-feature coordinates in the current clock, poster and blinds regions. For each target feature it triangulates from the same two neighboring timestamps and predicts the target ray under each model. The report includes missing support, failed triangulations and signed residuals. The regions and neighbor interval belong to this recording-specific diagnostic; it is not a generic accuracy benchmark. Both pose solutions and the associations come from related data, so this measures consistency rather than independent camera accuracy. Run `test_targeted_geometry_tracks` for analytic projection and triangulation checks.


`compare_splat_resolutions.py LOW_MANIFEST LOW_RUN HIGH_MANIFEST HIGH_RUN NEW_REPORT` scores a 2048 render after exact 2× area reduction against fixed 1024 source captures. It requires matching equirectangular camera IDs with exactly scaled parameters, identical pose rows and scene transforms, identical capture identities, exact reduced support and valid reference RGB. Saved reference files may differ from prepared RGB by at most one level; scoring uses the prepared source, matching `compare_splat_pixels.py`. The report preserves input, camera, configuration, render and mask hashes. It does not save resampled images or align the renders. Run `test_compare_splat_resolutions` for projection, reference and support rejection checks.

For end-to-end reconstructions whose camera poses were estimated separately, add `--allow-estimated-pose-change` to the comparison command. This opt-in permits different pose rows but still validates each compared image's camera ID and finite normalized pose, exact capture identity and source/mask checks, scaled ERP cameras, equal scene transforms, and disabled evaluation alignment. The report records both pose hashes and labels the result as a comparison at corresponding observed captures; it combines pose and reconstruction changes and is not an isolated resolution comparison.

### Temporal depth support diagnostic

`temporal_depth_roi.py` tests whether masked training images support local depth hypotheses in a fixed ROI. For example, with the prepared dataset and original SfM model paths used in the quality plan:

```sh
uv run --offline --isolated --no-project --python 3.14 --with-requirements vendor/360DVO/requirements-macos-arm64-py314.lock python -B tools/native-sfm/temporal_depth_roi.py PREPARED MODEL NEW_OUTPUT_DIR --reference 1435 --neighbors 1420 1425 1430 1445 1450 1455 --roi 400 330 140 35 --timeout 240
```

This CPU diagnostic currently uses camera 0 at 1024×512. It requires distinct training-frame neighbors and reports provisional matches and rejections; it does not create seed points. Depth search bounds and poses come from the supplied SfM model, which may have used evaluation frames. Patches assume locally constant radial depth, two-neighbor matches cannot receive the leave-one-out check, and repetitive or untextured regions may remain unknown. The results are not independent depth ground truth.

### Local capture-group diagnostic

`prepare_capture_group.py` stages original capture images, masks and camera rows as hardlinks for a local fitting diagnostic. Pass a prepared manifest and a new output directory, followed by `--train` and `--eval` names. The helper requires distinct names, requires training selections to be original training rows, checks pose and camera IDs against the manifest, verifies the seed hash, and records the staged source and mask hashes. An original training capture named as evaluation is relabeled for the diagnostic while keeping its pose and pixels; it is not thereby an independent heldout. Keep the original evaluation split unchanged in the full reconstruction. Run the focused check with `python3 -m unittest -v test_prepare_capture_group` from this directory. See `docs/research/one-view-detail-diagnostic.md` for the completed diagnostic and its limits.


`audit_seed_gauge.py ORIGINAL_MODEL NATIVE_MODEL PREPARED NEW_OUTPUT` checks native-2048 points against their own cameras and after a similarity transform into the original 1024 camera model. It verifies binary ERP camera/pose files and reports training-track support, residuals, triangulation angles and regional failures without exporting seed points. The current regions and 824-camera expectation belong to this recording diagnostic. Run `test_audit_seed_gauge` for camera, similarity, projection and conditioning checks.

`audit_signed_bearing.py MODEL PREPARED POINT_TRACKS_JSON_GZ RESOLVED_CALIBRATION_JSON NEW_REPORT --timeout 160` summarizes in-sample signed native-2048 ERP reprojection residuals by lens, nominal lens radius, image tile, track support, parallax and depth. It verifies the native ERP camera model and point-track provenance, rejects duplicate training source names, and hashes every training mask it reads. Nominal lens axes derive from embedded calibration; source-coordinate and applied lens-1 alignment provenance remain incomplete. The observations entered SfM, so low residuals and directional coherence do not establish calibration accuracy or independently validate depth.


`dis_depth_pilot.py PREPARED MODEL NEW_OUTPUT` is a recording-specific diagnostic for native 2048-pixel ERP temporal correspondence in the blinds region. It uses fixed training frames 1435, 1430, 1445 and 1450, rotation-initialized DIS flow, forward/backward checks, spherical triangulation and patch ambiguity tests. It writes a small report and overlay, never a seed model. Its fixed frame IDs and region are deliberate experiment inputs, not a general frame-selection policy. Run `test_dis_depth_pilot` in the external pinned UV runtime for known-depth, periodic-boundary, masking and repeated-pattern tests.


### Local surface and detail diagnostics

`poster_plane_sweep.py PREPARED ORIGINAL_MODEL NEW_OUTPUT_DIR` tests a measured poster-plane hypothesis against neighboring native spherical observations. Its default mode requires a distinguishable depth peak. `--fixed-plane-prior` instead prepares source-colored initialization points at the measured plane and reports their ambiguity. The fixed capture selection is an experiment specification, not a general scene mesher. `prepare_poster_seed_fit.py --help` stages matched seed/no-seed controls while preserving original cameras and source hashes; it does not start training.

`compare_planar_transfer.py DATA ZERO_RENDER_DIR PRIOR_JSON FOOTPRINT_JSON NEW_OUTPUT_DIR --original-model ORIGINAL_MODEL` compares source texture projected through that plane with retained Gaussian renders on the same predeclared footprint. Optional `--neighbor-data` and `--neighbor-zero` add the two existing adjacent-camera controls. It uses native ERP pixel centers, requires valid source interpolation neighborhoods, checks the original camera gauge, and records the unresolved difference from the earlier SfM pixel convention. Continuous display crops remain inside the measured source hull; scoring support is unchanged and shown separately. These are diagnostic resamplings, not extra camera observations or training images.

Run the focused checks with the external UV environment shown above and `python -B -m unittest test_poster_plane_sweep test_prepare_poster_seed_fit test_compare_planar_transfer`. The tests cover nonidentity plane projection, pixel centers, ambiguous repeating texture, mask support, longitude wrapping and point-cloud initialization.
