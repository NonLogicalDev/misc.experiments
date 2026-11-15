#!/bin/sh
# Download tested macOS/arm64 artifacts into an untracked local cache.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
mode=${1:-all}
case "$mode" in cpu|gpu|all) ;; *) echo 'Usage: fetch-runtime.sh [cpu|gpu|all]' >&2; exit 2 ;; esac
if [ "$(uname -s)-$(uname -m)" != Darwin-arm64 ]; then
  echo 'These locked wheels are for macOS Apple Silicon and Python 3.14.' >&2
  exit 1
fi
command -v python3.14 >/dev/null || { echo 'Python 3.14 is required.' >&2; exit 1; }
cache="$root/.artifacts"
mkdir -p "$cache"
tmp=$(mktemp -d "$cache/.fetch.XXXXXXXX")
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
fetch_wheels() {
  name=$1
  requirements=$2
  mkdir -p "$tmp/$name" "$cache/$name"
  python3.14 -m pip download --only-binary=:all: --require-hashes -r "$requirements" -d "$tmp/$name"
  for wheel in "$tmp/$name"/*.whl; do mv -f "$wheel" "$cache/$name/"; done
}
if [ "$mode" = cpu ] || [ "$mode" = all ]; then
  fetch_wheels cpu-wheels "$root/requirements.txt"
fi
if [ "$mode" = gpu ] || [ "$mode" = all ]; then
  fetch_wheels gpu-wheels "$root/vendor/360dvo-port/requirements-macos-arm64-py314.lock"
  command -v curl >/dev/null || { echo 'curl is required to download the model.' >&2; exit 1; }
  curl --fail --location --retry 2 --connect-timeout 15 --silent --show-error \
    'https://drive.usercontent.google.com/download?id=17x0V5DnXye5f1qlWLK80yRG6luInPmid&export=download&confirm=t' \
    -o "$tmp/360dvo.pth"
  python3.14 - "$tmp/360dvo.pth" <<'PY'
import hashlib
import pathlib
import sys
path = pathlib.Path(sys.argv[1])
digest = hashlib.file_digest(path.open('rb'), 'sha256').hexdigest()
expected = 'ae4c7d6c96f1fe9eb784174e757b173a80beff8654c7572cde817df95d602d2c'
if digest != expected:
    raise SystemExit(f'Model checksum mismatch: {digest}')
PY
  mv -f "$tmp/360dvo.pth" "$cache/360dvo.pth"
fi
printf 'Verified artifacts are in %s\n' "$cache"
