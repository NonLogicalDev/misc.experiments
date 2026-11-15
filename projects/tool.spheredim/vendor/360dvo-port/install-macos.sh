#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ "$(uname -s)-$(uname -m)" != Darwin-arm64 ]; then
  echo 'This runtime is for macOS Apple Silicon only.' >&2
  exit 1
fi
command -v python3.14 >/dev/null || { echo 'Python 3.14 is required.' >&2; exit 1; }
mkdir -p "$root/work"
if [ -e "$root/work/source" ] || [ -e "$root/work/env" ]; then
  echo 'work/source or work/env already exists; preserve it or choose a clean copy.' >&2
  exit 1
fi
cache="$root/../../.artifacts"
if [ ! -f "$cache/360dvo.pth" ]; then
  echo 'Fetch the GPU runtime first: scripts/fetch-runtime.sh gpu (from the project root)' >&2
  exit 1
fi
printf '%s  %s\n' 'ae4c7d6c96f1fe9eb784174e757b173a80beff8654c7572cde817df95d602d2c' "$cache/360dvo.pth" | shasum -a 256 -c
# A fresh project checkout has the layer definitions but not their local Git metadata.
if [ ! -e "$root/layers/.git" ]; then
  git -C "$root/layers" init -q
  git -C "$root/layers" add README.md layers
  git -C "$root/layers" -c user.name='SphereDim local setup' -c user.email='spheredim-local@localhost' commit -qm 'Initialize local layer definitions'
fi
(cd "$root/layers" && "$root/run-layerctl.sh" check)
(cd "$root/layers" && "$root/run-layerctl.sh" projection create spheredim-port --worktree "$root/work/source")
python3.14 -m venv "$root/work/env"
"$root/work/env/bin/python" -m pip install --no-index --find-links "$cache/gpu-wheels" --require-hashes -r "$root/requirements-macos-arm64-py314.lock"
echo 'Installed. See README.md for running and validation.'
