#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if [ "$(uname -s)-$(uname -m)" != Darwin-arm64 ]; then
  echo 'This offline runtime is for macOS Apple Silicon only.' >&2
  exit 1
fi
command -v python3.14 >/dev/null || { echo 'Python 3.14 is required.' >&2; exit 1; }
mkdir -p "$root/work"
if [ -e "$root/work/source" ] || [ -e "$root/work/env" ]; then
  echo 'work/source or work/env already exists; preserve it or choose a clean copy.' >&2
  exit 1
fi
(cd "$root" && shasum -a 256 -c runtime/SHA256SUMS)
# A fresh project checkout has the layer definitions but not their local Git metadata.
if [ ! -e "$root/layers/.git" ]; then
  git -C "$root/layers" init -q
  git -C "$root/layers" add README.md layerctl-offline.sh layers vendor
  git -C "$root/layers" -c user.name='SphereDim local setup' -c user.email='spheredim-local@localhost' commit -qm 'Initialize local layer definitions'
fi
LAYERCTL_BIN="$root/run-layerctl.sh" "$root/layers/layerctl-offline.sh" check
LAYERCTL_BIN="$root/run-layerctl.sh" "$root/layers/layerctl-offline.sh" projection create spheredim-port --worktree "$root/work/source"
python3.14 -m venv "$root/work/env"
"$root/work/env/bin/python" -m pip install --no-index --find-links "$root/runtime/wheelhouse" -r "$root/work/source/requirements-macos-arm64-py314.lock"
echo 'Installed. See README.md for running and validation.'
