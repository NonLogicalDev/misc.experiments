# Insta360 export

`stitch_insv.py` uses [insta360-rs 0.2.1](https://github.com/OpenSpeleo/insta360-rs) to stitch a compatible INSV recording as one equirectangular video on a GPU. It does not extract perspective views. The default FlowState mode levels the horizon while retaining camera heading; direction lock is not used. Audio is copied when the source and output container support it.

```sh
uv run --script scripts/stitch_insv.py input.insv output.mp4
```

Use `--width 5760` to select the panorama width, `--stabilization off` for camera-relative coordinates, and `--audio drop` if audio should be omitted. See `--help` for options. The first run lets uv obtain the pinned package and its dependencies; no wheel or model artifact is committed here. The package contains resources whose original terms apply: consult the upstream NOTICE as well as its Apache-2.0 source license.

Rolling-shutter correction defaults to `off`. This permits a single per-frame rotation to map a camera-relative mask into the stabilized image; `--rolling-shutter auto` enables the upstream correction but that single-rotation assumption then does not hold. Export does not itself remove an operator: supply and verify a suitable exclusion mask before reconstruction. Horizon leveling is an orientation estimate, and heading can drift. Neither the video nor IMU rotation provides camera translation or metric scale.

On Apple hardware, a one-second X5 INSV test exported 30 frames with GPU processing, FlowState and copied AAC audio. This is a compatibility test of that file and machine; other cameras and AMD GPUs have not been tested here.

## Motion and masking

The [Rust X5 orientation extractor](../tools/insv-imu/README.md) writes per-sample IMU data and an estimated orientation at each video frame. Its dependencies are pinned in Cargo; build products and recordings stay outside Git. It was verified on one X5 recording. It does not recover position, and relative yaw may drift.

For an OFF export and a FlowState export made from the same source with rolling-shutter correction off, `scripts/warp_insv_mask.py` maps a camera-relative, white-means-exclude equirectangular mask into FlowState coordinates using the per-frame orientation CSV. The `top40` mask is an example, not a general operator detector. Optional transition arguments expand that example to a different top fraction after a specified time; they do not detect people. Use a mask appropriate to the recording and verify coverage, including between sampled frames. The output is a lossless grayscale video, not a masked panorama; apply it to the matching FlowState video before use.

`scripts/convert_insv_poses.py` converts 360DVO camera-to-world rotations from the OFF panorama to the corresponding FlowState panorama while preserving positions. Both scripts need the Python dependencies installed for the portable 360DVO backend, plus FFmpeg; run them through its uv-managed environment. Their alignment assumes matching frame timestamps and has only been checked on the tested recording. The operator mask must also be enforced in tracking, including feature support and correspondence targets; a black image alone can produce misleading features at its boundary.

For a constant-rate 30000/1001 fps FlowState video and a matching mask with the same frame count, this example applies an opaque black mask and copies audio from the recording. The explicit timestamp reset prevents the mask stream's time base from changing playback duration. Adjust the rate to the source and verify output frame count and duration; the mask and video must start on the same frame.

```sh
ffmpeg -i flow-state.mp4 -i mask.nut -i input.insv \
  -filter_complex '[0:v]settb=1/30000,setpts=N*1001,format=gbrp,split[base][b];[b]lutrgb=r=0:g=0:b=0[black];[1:v]settb=1/30000,setpts=N*1001,format=gbrp[mask];[base][black][mask]maskedmerge[out]' \
  -map '[out]' -map 2:a:0 -frames:v "$(ffprobe -v error -select_streams v:0 -show_entries stream=nb_frames -of csv=p=0 flow-state.mp4)" -fps_mode cfr -r 30000/1001 \
  -c:v libx264 -crf 18 -c:a copy masked-flow-state.mp4
```

Mask generation uses bilinear interpolation at its boundary; its default four-pixel source-space dilation is intended as a margin, not proof that the operator is fully hidden. Confirm opacity and coverage in the output, especially during fast motion and at transitions. Do not use a partially transparent mask for reconstruction.
