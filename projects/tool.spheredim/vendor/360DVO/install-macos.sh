#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
work="$root/work"
if [ "$(uname -s)-$(uname -m)" != Darwin-arm64 ]; then
  echo 'This runtime is for macOS Apple Silicon only.' >&2
  exit 1
fi
command -v uv >/dev/null || { echo 'uv is required.' >&2; exit 1; }
if [ -e "$work" ]; then
  echo 'vendor/360DVO/work already exists; preserve it or choose a clean copy.' >&2
  exit 1
fi
cache="$root/../../.artifacts"
if [ ! -f "$cache/360dvo.pth" ]; then
  echo 'Fetch the GPU runtime first: scripts/fetch-runtime.sh gpu (from the project root)' >&2
  exit 1
fi
printf '%s  %s\n' 'ae4c7d6c96f1fe9eb784174e757b173a80beff8654c7572cde817df95d602d2c' "$cache/360dvo.pth" | shasum -a 256 -c
# A fresh project checkout has the layer definitions but not their local Git metadata.
if [ ! -e "$root/.git" ]; then
  git -C "$root" init -q
  git -C "$root" add layers
  git -C "$root" -c user.name='SphereDim local setup' -c user.email='spheredim-local@localhost' commit -qm 'Initialize local layer definitions'
fi
(cd "$root" && "$root/../../scripts/layerctl.sh" check)
(cd "$root" && "$root/../../scripts/layerctl.sh" projection create spheredim-port --worktree "$work")
uv run --isolated --no-project --python 3.14 --no-build --with-requirements "$root/requirements-macos-arm64-py314.lock" python -c 'import torch; print(torch.__version__)'
echo 'Installed. See README.md for running and validation.'
