# Source dependencies and binary procurement

- `colmap/` is a Git submodule pinned to COLMAP 4.2.1, commit `bd1fcf654d2dd8fefa1466999c190a246f83f4b9`. Its upstream license is in `colmap/COPYING.txt`.
- `ffmpeg/` is a Git submodule pinned to FFmpeg n8.0.1, commit `894da5ca7d742e4429ffb2af534fcda0103ef593`. Its license and build conditions are in `ffmpeg/LICENSE.md` and `ffmpeg/COPYING.LGPLv2.1`.
- From the SphereDim project root, initialize both with `git submodule update --init -- vendor/colmap vendor/ffmpeg`. A normal Git clone does not populate submodules automatically. The upstream repositories include their own documentation images and test fixtures; those are not tracked as blobs in the enclosing repository.
- `scripts/fetch-runtime.sh` downloads pinned PyCOLMAP, NumPy and GPU wheels and the model into the ignored `.artifacts/` cache, verifying SHA-256 hashes. It does not build those wheels from source. AMD runtime dependencies remain unverified.

FFmpeg is built from the submodule using `scripts/build_ffmpeg.sh`. The current tracker uses an upstream PyCOLMAP binary wheel; it has not been rebuilt from the pinned COLMAP source, and the wheel's C++ dependencies are not all provided as source here.
