# Scene complexity validation

All tracking runs use whole equirectangular frames with the same SphereDim settings. These runs used PyCOLMAP 4.2.1, the FFmpeg 8.0.1 decoder, and Blender 5.1.0 for synthetic rendering and pose import. Result directories preserve text references, recovered poses where available, and metrics or failure logs. Binary clips and Blender files are not tracked; regenerate or fetch them using the instructions below. No virtual perspective views were extracted.

| Scene | Type | Registration | Trajectory RMS / reference path | Worst frame image p95 | Result |
|---|---|---:|---:|---:|---|
| `plain` | Synthetic, very low texture | No reconstruction | — | — | Failed to initialize |
| `repetitive` | Synthetic, repeated checker patterns | 24/24 | 0.116% | 0.447% | Passed |
| `low_light` | Synthetic, dark with added noise | 24/24 | 0.153% | 0.570% | Passed |
| `bridge_night` | Real, nighttime bridge with reflections | 40/40 | 3.149% | Not measured | Above trajectory target |
| `grove` | Real, drone over grass and trees | 40/40 | 0.068% | Not measured | Passed trajectory target |
| `indoor_RC_car` | Real, indoor RC vehicle | 40/40 | 1.101% | Not measured | Above trajectory target |

The synthetic cases are deliberately controlled stress tests with simple procedural geometry, not photorealistic replicas. Their original images are rendered at 1024×512 and 8 fps; the test clips add H.264 compression, mild lens distortion, and noise. The dark case uses stronger added noise. Ground-truth camera poses and sampled visible scene points come from Blender. The `plain` test has little texture and no usable output, so it has no numeric accuracy estimate. A separate attempt with more permissive features still registered fewer than three poses.

The real clips sample every second frame of the first 79 frames of the named [360DVO](https://huggingface.co/datasets/chris1004336379/360DVO) sequences and encode them at 5 fps; the tracker works at 2048×1024. Per-frame source paths and hashes are in each real case's `manifest.json`. We assume the first trajectory row corresponds to source image `0001.jpg` and use every second reference row. The bridge and grove frame counts match their reference row counts; this supports but does not independently prove the ordering. The dataset's reference trajectories come from Metashape reconstruction, rather than independent physical measurement. Real image-alignment error could not be measured because these clips do not provide independently measured 3D surface points. The bridge and RC clips contain fixed image overlays; their effect on tracking is not established. The RC result contains one large isolated position error, while the bridge discrepancies occur across multiple frames.

For all measured runs, trajectory error is computed after a single best-fit similarity alignment and is normalized by full reference path length. Image error uses normalized equirectangular coordinates with horizontal wrap and is the largest per-frame 95th-percentile distance. These are short clips and a limited number of scenes, not a guarantee for other footage or longer recordings.

The synthetic clips and scene generator are project test artifacts. The real clips and trajectory references are derived from 360DVO by Xiaopeng Guo, Yinzhe Xu, Huajian Huang and Sai-Kit Yeung, distributed under [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/). Their noncommercial share-alike conditions apply to those data and derived clips.

To repeat the synthetic suite with fresh renders, use a Blender executable and an FFmpeg with `libx264` on `PATH`:

```sh
.venv/bin/python tests/run_synthetic_suite.py /path/to/new-results --blender /path/to/blender --encoder /path/to/ffmpeg
```

The command returns a nonzero exit code if any scene fails. That is expected for the `plain` scene on the tested prototype. `summary.json` and individual logs identify which stage failed. A complete fresh rerun produced the same pass/fail outcomes; its measurements are in `synthetic-repeat.json`.

See [RECREATE.md](../RECREATE.md) for complete media download and regeneration commands.
