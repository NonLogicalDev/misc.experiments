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
