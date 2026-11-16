# Source dependencies and binary procurement

- `colmap/` is a Git submodule pinned to COLMAP 4.2.1, commit `bd1fcf654d2dd8fefa1466999c190a246f83f4b9`. Its upstream license is in `colmap/COPYING.txt`.
- `ffmpeg/` is a Git submodule pinned to FFmpeg n8.0.1, commit `894da5ca7d742e4429ffb2af534fcda0103ef593`. Its license and build conditions are in `ffmpeg/LICENSE.md` and `ffmpeg/COPYING.LGPLv2.1`.
- From the SphereDim project root, initialize both with `git submodule update --init -- vendor/colmap vendor/ffmpeg`. A normal Git clone does not populate submodules automatically. The upstream repositories include their own documentation images and test fixtures; those are not tracked as blobs in the enclosing repository.
- `scripts/fetch-runtime.sh` uses uv to resolve pinned PyCOLMAP, NumPy and GPU dependencies and downloads the verified model into the ignored `.artifacts/` cache. It does not build those wheels from source. AMD runtime dependencies remain unverified.

FFmpeg is built from the submodule using `scripts/build_ffmpeg.sh`. The current tracker uses an upstream PyCOLMAP binary wheel; it has not been rebuilt from the pinned COLMAP source, and the wheel's C++ dependencies are not all provided as source here.

## Layered integrations

- [360DVO](360DVO/README.md): pinned upstream plus the portable GPU inference layer. Generated source lives directly in ignored `vendor/360DVO/work/`; Python environments live in uv’s external cache.
- [insta360-rs](insta360-rs/README.md): pinned upstream plus the observation export layer. Its README records build and sample validation.

Both use the shared [layerctl helper](../scripts/layerctl.sh), which runs the pinned external Go tool. FFmpeg build outputs live in ignored `.artifacts/ffmpeg-runtime/`; `vendor` contains source integrations, not installed runtime binaries.
