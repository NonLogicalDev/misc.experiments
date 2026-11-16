#!/bin/sh
# Verify the tested macOS ARM64 dependencies with uv and fetch the model.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
mode=${1:-all}
case "$mode" in cpu|gpu|all) ;; *) echo 'Usage: fetch-runtime.sh [cpu|gpu|all]' >&2; exit 2 ;; esac
if [ "$(uname -s)-$(uname -m)" != Darwin-arm64 ]; then
  echo 'These locked wheels are for macOS Apple Silicon and Python 3.14.' >&2
  exit 1
fi
command -v uv >/dev/null || { echo 'uv is required.' >&2; exit 1; }
cache="$root/.artifacts"
mkdir -p "$cache"
tmp=$(mktemp -d "$cache/.fetch.XXXXXXXX")
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
warm_cache() {
  requirements=$1
  uv run --isolated --no-project --python 3.14 --no-build --with-requirements "$requirements" python -c 'import sys; print("Runtime:", sys.prefix)'
}
if [ "$mode" = cpu ] || [ "$mode" = all ]; then
  warm_cache "$root/requirements.txt"
fi
if [ "$mode" = gpu ] || [ "$mode" = all ]; then
  warm_cache "$root/vendor/360DVO/requirements-macos-arm64-py314.lock"
  command -v curl >/dev/null || { echo 'curl is required to download the model.' >&2; exit 1; }
  expected='ae4c7d6c96f1fe9eb784174e757b173a80beff8654c7572cde817df95d602d2c'
  if [ -f "$cache/360dvo.pth" ] && printf '%s  %s\n' "$expected" "$cache/360dvo.pth" | shasum -a 256 -c; then
    : # Reuse the verified local model.
  else
    curl --fail --location --retry 2 --connect-timeout 15 --silent --show-error \
      'https://drive.usercontent.google.com/download?id=17x0V5DnXye5f1qlWLK80yRG6luInPmid&export=download&confirm=t' \
      -o "$tmp/360dvo.pth"
    printf '%s  %s\n' "$expected" "$tmp/360dvo.pth" | shasum -a 256 -c
    mv -f "$tmp/360dvo.pth" "$cache/360dvo.pth"
  fi
fi
printf 'Verified dependencies with uv; model (if requested) is in %s\n' "$cache"
