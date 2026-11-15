# SphereDim

SphereDim estimates a camera trajectory from a full, unwrapped 2:1 equirectangular 360° video. It extracts complete panorama frames, then uses COLMAP's EQUIRECTANGULAR camera model for CPU feature matching and spherical structure from motion. It does not create perspective views or cubemaps.

## Experimental GPU backend

The [portable 360DVO backend](vendor/360dvo-port/README.md) runs full equirectangular inference on Apple MPS and is designed for ROCm. Its setup, Blender export, accuracy evidence, and current AMD limitations are documented separately.

The experimental GPU backend runs the user's `layerctl` directly with Go at a pinned revision.

## Setup

Requires CPython 3.14 on macOS arm64 for the pinned wheels, a C compiler and `make` to build FFmpeg, and Blender 5.x to import the animation. Other Python and platform combinations require compatible PyCOLMAP and NumPy builds.

```sh
scripts/fetch-runtime.sh cpu
python3 -m venv .venv
.venv/bin/pip install --no-index --find-links .artifacts/cpu-wheels --require-hashes -r requirements.txt
scripts/build_ffmpeg.sh
```

## Track a video

```sh
.venv/bin/python src/spheredim.py path/to/video.mp4 path/to/new-output
```

The output directory must be absent or empty. By default, sampling uses the source average frame rate, so constant-frame-rate videos are processed at their original rate. `--fps` can select a different rate. Sampling produces a constant-rate timeline; output timestamps start at zero and correspond to the resampled video, not source packet timestamps for variable-frame-rate footage. Lower `--fps` to reduce processing time, at the cost of temporal coverage. Move the camera through the scene, not just rotate it in place. Camera position is recovered up to an unknown global rotation, translation, and scale; distances are not meters unless aligned to a known measurement.

- `poses.json` contains every sampled frame, time, and a row-major 3×4 camera-to-world transform; missing poses are `null`.
- `poses.csv` contains the same information as numeric columns; unregistered poses have empty matrix fields.
- `frames/`, `database.db`, and `sparse/` retain the input samples and COLMAP reconstruction for inspection. If there are disconnected models, the exported poses come from the largest model only.

The camera coordinate system in the interchange files is COLMAP's: X right, Y down, Z forward. World axes and scale are arbitrary. This is offline reconstruction, and sampling means output poses are not necessarily available for every source frame. Some scenes will fail or produce gaps. COLMAP's conventional SIFT features do not fully account for equirectangular distortion and wraparound; moving objects, stitch seams, blur, and textureless scenes can reduce quality.

## Blender

In Blender's Scripting workspace, run `src/blender_import.py` with the command below, or run it in the background to create a `.blend` using an additional save script:

```sh
blender --python src/blender_import.py -- path/to/new-output/poses.json
```

The script adds an animated panoramic camera to the current scene. Its keyframes use the existing scene frame rate. Blender interpolates across missing samples, including unregistered gaps; those interpolated positions are not measured poses. The project is not saved automatically. Requires Blender 5.x.

## Checks

```sh
.venv/bin/python -m unittest discover -s tests
```

`tests/render_scene.py` renders a native equirectangular camera and known trajectory in Blender Cycles for an end-to-end experiment. It uses Cycles because the panoramic camera is supported there. Test captures and reconstructions can be large; keep them outside the source tree.

The original `validation/` capture was rendered at 1024×512 and 4 fps for 20 frames, with translation and rotation inside a textured scene. The encoded video applies FFmpeg `lenscorrection=k1=0.003:k2=0`, temporal uniform noise with strength 2, and H.264 compression at CRF 16. These distortions are a controlled test, not a calibrated model of any particular camera. The Blender import can be recreated with `tests/check_import.py`; `truth.json`, `poses.json`, `distorted-imported.json`, and `metrics.json` preserve the comparison. Position errors are in synthetic scene units after a single 7-DoF similarity alignment; orientation errors use that same world rotation.

To reproduce the synthetic experiment, render with `blender --background --python tests/render_scene.py -- /tmp/spheredim-render`, encode the numbered PNGs at 4 fps with the filter above, track that video at `--fps 4 --width 1024`, and run `tests/check_import.py` in Blender followed by `tests/evaluate.py` in the project virtual environment. The import checker takes the importer path, pose JSON, and an output basename after `--`; the evaluator takes ground-truth JSON, pose JSON, and the imported-matrix JSON. Use an empty directory for each new run.

## Accuracy experiments

The `validation/loop/` experiment rendered 48 frames of a camera moving through a textured scene while rotating through a full turn. The video includes mild lens distortion, noise, and compression. The source renderer ray-casts 512 scene points per frame to record visible 3D points independently of the tracker. Run:

```sh
.venv/bin/python tests/check_accuracy.py validation/loop/truth.json validation/loop/poses.json validation/loop/loop-imported.json
```

Camera positions are aligned once to the known ground truth with a similarity transform because monocular SfM cannot recover absolute position, orientation, or scale. Trajectory error is position error divided by the full known path length. Image error is the Euclidean distance between the projected and true equirectangular coordinates, after normalizing horizontal and vertical coordinates by their respective dimensions and wrapping horizontally across the seam. The check requires every frame to be registered, trajectory position RMS below 1% of path length, and the 95th percentile of image displacement below 1% in each frame. It also reports the worst image point. It does not measure occluded pixels or prove performance on other scenes.

`validation/real/` records a 50-frame sample from the 360DVO `tokyo_citywalk` sequence. Its manifest records the original frame paths and hashes; the included reference trajectory is attributed to the 360DVO dataset under CC-BY-NC-SA-4.0. The reference was generated with SfM and is not independent physical ground truth. The real test currently measures trajectory only, not image alignment.

The tracker and video decoder run in compiled C++ and C code. Python orchestrates the pipeline and Blender importer. Vendored COLMAP source and the pinned macOS arm64 wheels and download recipe are described in `vendor/README.md`; the wheel has not been rebuilt from the vendored source, and its own C++ build dependencies are not yet fully vendored as source. SphereDim prefers its compiled vendored FFmpeg when present and otherwise uses FFmpeg on PATH.

A second synthetic experiment in `validation/dynamic/` uses a different randomized scene and a moving object. Its 32 frames all registered. With lossless frame extraction and tighter geometric filtering, trajectory RMS is 0.154% of path length and the worst frame image p95 is 0.606%. The largest individual image displacement is 2.28%; near poles, equirectangular longitude exaggerates small angular shifts, and nearby geometry is especially sensitive to translation. The experiment reports this maximum rather than treating every point as a guaranteed 1% bound.

Additional tests in [validation/complexity](validation/complexity/README.md) cover low texture, repeated patterns, low light, and three real 360° clips. The plain scene failed to initialize; the night bridge and indoor RC-car reference comparisons exceeded 1% trajectory RMS. Complete registration does not guarantee an accurate track.

Binary artifacts are not tracked. `scripts/fetch-runtime.sh` retrieves pinned wheels and model weights with SHA-256 verification into the ignored `.artifacts/` cache. Generated video and Blender files can be recreated as described in `validation/RECREATE.md`; existing local copies are in `.artifacts/originals/validation/`.
