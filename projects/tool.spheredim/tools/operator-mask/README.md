# Experimental operator mask conversion

`warp_sequence.py` converts a sequence of SAM masks from camera-relative OFF equirectangular frames to the matching horizon-leveled FlowState frames. White means keep; black means exclude. It produces only masks for the input samples, preserving each source frame index and presentation timestamp in `manifest.json`. It does not fill missing frames or judge whether the mask covers a person. Do not use its output for reconstruction until coverage has been checked for every frame that reconstruction will consume, including moving limbs and the panorama seam.

The conversion assumes the fused orientation CSV and both exports came from the same video, and the FlowState export had rolling-shutter correction **off**. It applies the same frame-by-frame output-to-input ray rotation as `scripts/warp_insv_mask.py`; yaw is preserved by that export. Input masks must be full 2:1 panoramas, named `frame_00000.png`, `frame_00001.png`, etc., with no gaps. `--first-frame` and `--stride` map each mask to its original frame number; do not infer timestamps from a sampled frame's ordinal alone. The guards are measured in pixels at the input mask resolution and wrap at the longitude seam and across the poles. `--guard` is applied before the warp; `--output-guard` expands the warped mask further in stabilized coordinates.

With the 360DVO port environment installed, from the SphereDim directory:

```sh
uv run --isolated --no-project --python 3.14 --with-requirements vendor/360DVO/requirements-macos-arm64-py314.lock python tools/operator-mask/warp_sequence.py \
  /path/to/sam-masks /path/to/orientation_frames_fused.csv /path/to/new-output \
  --first-frame 0 --stride 15 --guard 4 --output-guard 32
uv run --isolated --no-project --python 3.14 --with-requirements vendor/360DVO/requirements-macos-arm64-py314.lock python -m unittest discover -s tools/operator-mask -p 'test_*.py' -v
```

Spirula Studio's `sam track` can generate candidate masks from full ERP images on its Vulkan backend using a local SAM 2.1 checkpoint and visual points. Its default output is white=keep. Never use `sam extract` with a 360 view conversion: supply the full unwrapped frames directly. For an experiment on the 2018 Insta360 recording, `--point 450,45 --point 510,135 --dilate-ratio 0.15` on 1024×512 camera-relative frames segmented head and torso in initial samples. These point coordinates are specific to that recording and resolution, not a general detector. The model tracked body motion in sparse late samples but also included nearby fabric, and a head-only click missed the torso. The 2 Hz test used a 4-pixel source guard plus a 32-pixel output guard to cover conspicuous missed legs and seam-side regions; the reviewed first 69 seconds excluded a median 11.62% of spherical area. This is a recording-specific visual check, not pixel-level ground truth. No sample set proves coverage between frames. Fine boundary errors, body parts at the seam, and tracker failure require explicit review.

The model used for the experiment was `sam2.1_hiera_tiny_f16.ggml`, SHA-256 `98ea059bb39bcf42a3109ee14ab3d25650adb737e896362716e2737d7833ae95`, from [sam3.cpp's model distribution](https://huggingface.co/PABannier/sam3.cpp/resolve/main/sam2.1_hiera_tiny_f16.ggml). SAM 2.1 is [Apache-2.0](https://github.com/facebookresearch/sam2/blob/main/LICENSE). Fetch model artifacts separately; do not commit them. The tested GPU was an Apple M2 Pro through Vulkan/MoltenVK. AMD behavior and full-frame operator coverage are not validated.

For a bounded candidate run, `run_candidate_sequence.py` extracts camera-relative and stabilized full ERP images at identical source indices, checks each sampled video PTS against the fused orientation CSV, runs one continuous SAM track, warps the resulting masks, and creates labeled contact sheets. Its output is **unreviewed**; contact-sheet creation does not approve or promote masks. It refuses an existing output directory, leaves `INCOMPLETE` on failure, and checks the output budget and free-space reserve while each subprocess runs. The example prompts are recording-specific and must be reviewed for a different recording. `--config-dir` must point to the existing Spirula configuration in which the applicable model license was accepted.

```sh
python tools/operator-mask/run_candidate_sequence.py \
  --off-video "$RECORDING/panorama-unstabilized.mp4" \
  --stable-video "$RECORDING/panorama-horizon-stable-mask-ready.mp4" \
  --fused-csv "$RECORDING/orientation/fused/orientation_frames_fused.csv" \
  --model "$MODEL" --spirula "$SPIRULA" --config-dir "$SPIRULA_CONFIG" \
  --output "$NEW_OUTPUT" --count 412 --stride 5 --budget-mib 700 --reserve-gib 35
```

The command uses FFmpeg, ffprobe, uv, the cached locked Python dependencies, and a local Vulkan-capable Spirula executable. It covers source frames 0–2055, not the final seconds of the recording. Inspect every sheet and handle mask failures before reconstruction. Preserve the original reviewed masks separately.

Before promoting a visually reviewed set, run `uv run --isolated --no-project --python 3.14 --with-requirements vendor/360DVO/requirements-macos-arm64-py314.lock python tools/operator-mask/verify_candidates.py /path/to/review/manifest.json`. The verifier checks the source manifest, each image and mask, and each sheet against their recorded hashes and frame order. A successful check proves only that these files are unchanged; it does not attest that a person reviewed them or that operator coverage is correct. Earlier review manifests without individual hashes must be regenerated and reviewed again.

`propagate_candidates.py` is a CPU experiment for filling between sparse SAM keyframes, not an approval workflow. It reads actual full camera-relative ERP frames in `frame_00000.png` ordinal order and SAM keep masks at key ordinals (other SAM masks are optional comparison references). A source manifest supplies the same ordered source indices and PTS. It estimates adjacent bidirectional Farneback flow with longitude context, propagates both neighboring key masks, unions them and expands uncertain boundaries. Pole mapping uses reflection and a half-turn; optical-flow reliability at poles, occlusions, large displacements and moving limbs is not established. Output remains unreviewed; transform with the matching fused orientation and inspect every stabilized overlay before any use.

```sh
uv run --isolated --no-project --python 3.14 --with-requirements vendor/360DVO/requirements-macos-arm64-py314.lock python tools/operator-mask/propagate_candidates.py \
  /path/to/off-frames /path/to/ordinal-sam-masks /path/to/source-manifest.json /path/to/new-output \
  --key-stride 3 --guard 8 --max-frames 37
```

On one 37-frame pilot at source frames 0–180, propagation took 4.52 seconds excluding SAM and export. Visual review of all stabilized 512×256 overlays found no conspicuous body leaks, while several frames excluded visibly more scene than per-frame SAM. Of the 24 propagated frames, the mean SAM-excluded/candidate-kept difference was 378 pixels and the mean SAM-kept/candidate-excluded difference was 26,596 pixels at 1024×512. These are differences from SAM, not measured body leaks or false positives; SAM itself excluded sofa at frame 5. This brief sample does not validate the rest of the video, and neither those figures nor the elapsed time establishes end-to-end speedup.
