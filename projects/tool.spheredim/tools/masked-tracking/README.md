# SphereDim masked live tracker

Run with the SphereDim portable 360DVO environment and its source on `PYTHONPATH`:

```sh
PYTHONPATH="$SPHEREDIM/vendor/360DVO/work" \
uv run --isolated --no-project --python 3.14 --with-requirements "$SPHEREDIM/vendor/360DVO/requirements-macos-arm64-py314.lock" python track.py input.mp4 output \
  --weights "$SPHEREDIM/.artifacts/360dvo.pth" --device mps \
  --width 1024 --patches 96 --stride 5 --mask-top 0.4 --mask-guard 0.13
```

Specify both mask fractions for each video: `--mask-top` blanks the indicated top fraction before inference; `--mask-guard` excludes an additional band from feature selection and optimization. Values are fractions of image height. Set both to zero only if that is appropriate for the input. Near-black input regions are also rejected per frame, with a one-feature-cell dilation, from source patch selection and correspondence targets. These settings do not detect people: inspect all frames or use an appropriate external segmentation process before reconstruction. The guard needs to account for encoder and correlation support; the example values are not a universal guarantee. Results are monocular and have arbitrary scale. Optimization can fail or drift.

Writes atomic `progress.json`, partial `poses-progress.json` and `sparse-progress.ply`, and on success `poses.json`, `poses.csv` and `sparse.ply`. Poses are camera-to-world matrices. `make_blend.py` can import the output through Blender; pass only a suitably masked video when including a video background. `check_mask.py` runs focused mask behavior checks with the same environment and `PYTHONPATH`.

To align a Blender scene with gravity, first estimate the world-up direction from the original OFF-video 360DVO poses and matching fused IMU stream, then apply the resulting rotation to a new scene. The estimate reports disagreement between samples; it does not measure absolute accuracy.

```sh
PYTHONPATH="$SPHEREDIM/vendor/360DVO/work" \
uv run --isolated --no-project --python 3.14 --with-requirements "$SPHEREDIM/vendor/360DVO/requirements-macos-arm64-py314.lock" \
  python estimate_gravity.py poses-off.json orientation_frames_fused.csv gravity.json
blender -b --python align_gravity_blender.py -- scene.blend gravity.json aligned.blend
```

Use the unaligned scene and matching OFF poses as input, and do not apply the alignment twice. The resulting Blender parent rotates the camera, trajectory, and point cloud together; the original pose JSON and PLY retain their original world coordinates. The exporter supplies a point-color material and selects Cycles for panorama rendering.
