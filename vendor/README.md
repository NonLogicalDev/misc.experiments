# Vendored components

- `colmap/` is the unmodified COLMAP 4.2.1 source release, tag `4.2.1`, release commit `bd1fcf6`. Source archive SHA-256: `15fb9e333541676e4ee9bc5d8ab95a3ed6e549a20eb13fc5aafd04ca06c76c88`. License: `colmap/COPYING.txt`.
- `ffmpeg/` is the unmodified FFmpeg 8.0.1 source release. Source archive SHA-256: `05ee0b03119b45c0bdb4df654b96802e909e0a752f72e4fe3794f487229e5a41`. License and build conditions: `ffmpeg/LICENSE.md` and `ffmpeg/COPYING.LGPLv2.1`.
- `wheels/` contains the exact upstream PyCOLMAP 4.2.1 and NumPy 2.5.4 binary wheels for CPython 3.14 on macOS arm64. The wheels contain their licenses. They let that configuration install without network access.

The current production reconstruction calls the PyCOLMAP binary wheel. Vendoring COLMAP source does not mean that wheel was rebuilt locally from the vendored tree. The upstream PyCOLMAP wheel also bundles C++ dependencies; their build inputs are not all vendored as source here. Building COLMAP from source requires its C++ dependencies. See `colmap/vcpkg.json` and `colmap/doc/install.rst`. FFmpeg is built directly from its vendored source using `scripts/build_ffmpeg.sh`.
