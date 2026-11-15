#!/bin/sh
# Build the decoders and filters SphereDim uses without network or shared FFmpeg libraries.
set -eu
project=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
build="$project/.build/ffmpeg"
mkdir -p "$build"
cd "$build"
"$project/vendor/ffmpeg/configure" \
  --prefix="$project/vendor/runtime" \
  --disable-everything --disable-autodetect --disable-network \
  --disable-doc --disable-debug --disable-shared --enable-static --enable-zlib \
  --enable-ffmpeg --enable-ffprobe --disable-ffplay \
  --enable-protocol=file \
  --enable-demuxer=mov,matroska,mpegts,avi,image2 \
  --enable-muxer=image2 \
  --enable-decoder=h264,hevc,mjpeg,png,vp9,av1 \
  --enable-encoder=mjpeg,png \
  --enable-parser=h264,hevc,mjpeg,vp9,av1 \
  --enable-filter=fps,scale,format
make -j 4
make install
