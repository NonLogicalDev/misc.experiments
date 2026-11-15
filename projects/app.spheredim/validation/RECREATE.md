# Recreating validation media

`tests/recreate_media.py` produces full equirectangular videos outside the Git checkout. It requires Python 3, FFmpeg with `libx264`, and Blender for synthetic scenes. Each output must be a new or empty directory. It does not overwrite existing footage or create perspective views.

For the synthetic scenes, the project Blender renderer records its own ray-cast truth and the script adds the same lens correction, temporal noise and encoding settings used by the synthetic complexity suite:

```sh
python3 tests/recreate_media.py synthetic loop /path/to/new-loop --blender /path/to/blender --ffmpeg /path/to/ffmpeg
python3 tests/recreate_media.py synthetic dynamic /path/to/new-dynamic --blender /path/to/blender --ffmpeg /path/to/ffmpeg
python3 tests/recreate_media.py synthetic plain /path/to/new-plain --blender /path/to/blender --ffmpeg /path/to/ffmpeg
```

Other scenarios are `baseline`, `repetitive`, and `low_light`. Output is `input.mp4` and `truth.json`. Use the output truth with the rerendered video; renderer, FFmpeg, CPU/GPU, and encoder versions can change rendered samples or encoded bytes. The videos need not reproduce the original checksum or the originally reported metrics exactly.

For real footage, the script downloads the selected 360DVO dataset frames using the existing manifest, verifies every frame's SHA-256, and encodes them at the recorded sample rate. These data and their derived videos are CC-BY-NC-SA-4.0; see the corresponding manifest and dataset terms.

```sh
python3 tests/recreate_media.py real bridge_night /path/to/new-bridge
python3 tests/recreate_media.py real grove /path/to/new-grove
python3 tests/recreate_media.py real indoor_RC_car /path/to/new-indoor
python3 tests/recreate_media.py real tokyo_citywalk /path/to/new-tokyo
```

The output `input.mp4` is re-encoded; byte-for-byte identity with previously recorded videos is not guaranteed. The existing dataset manifests and text reference trajectories are retained in `validation/` for provenance and trajectory evaluation. For repeatable evaluation, regenerate the tracker output against the newly encoded video rather than assuming older poses match its pixels.

To recreate a Blender file from an existing pose JSON, run:

```sh
blender --background --factory-startup --python tests/check_import.py -- src/blender_import.py /path/to/poses.json /path/to/new-import
```

This writes `/path/to/new-import.blend` and `/path/to/new-import.json` with the imported camera animation. It does not reconstruct the synthetic source scene into that Blender file.
