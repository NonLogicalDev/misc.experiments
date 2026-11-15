# Vendored source and binary procurement

- `colmap/` contains COLMAP 4.2.1 source, release commit `bd1fcf6`; four binary documentation images are omitted. The [upstream release](https://github.com/colmap/colmap/releases/tag/4.2.1) supplies the full source. The previously downloaded source archive SHA-256 was `15fb9e333541676e4ee9bc5d8ab95a3ed6e549a20eb13fc5aafd04ca06c76c88`. License: `colmap/COPYING.txt`.
- `ffmpeg/` contains FFmpeg 8.0.1 source with the binary `tests/reference.pnm` fixture omitted. The [upstream release](https://ffmpeg.org/releases/ffmpeg-8.0.1.tar.xz) supplies the full source; the previous source archive SHA-256 was `05ee0b03119b45c0bdb4df654b96802e909e0a752f72e4fe3794f487229e5a41`. License and build conditions: `ffmpeg/LICENSE.md` and `ffmpeg/COPYING.LGPLv2.1`.
- `scripts/fetch-runtime.sh` downloads the pinned PyCOLMAP, NumPy, GPU wheels and model into `.artifacts/`, verifying SHA-256 hashes. It does not build those wheels from source. AMD runtime dependencies remain unverified.

FFmpeg is built from the source tree using `scripts/build_ffmpeg.sh`. The omitted FFmpeg fixture is not needed by that build; upstream source tests requiring it need the full release.
