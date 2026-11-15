#!/bin/sh
set -eu
project=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
source_dir="$project/vendor/util.layerctl"
if [ ! -f "$source_dir/go.mod" ]; then
  echo 'Initialize layerctl first: git submodule update --init vendor/util.layerctl' >&2
  exit 1
fi
command -v go >/dev/null || { echo 'Go 1.26 or newer is required on PATH.' >&2; exit 1; }
tmp=$(mktemp -d "${TMPDIR:-/tmp}/spheredim-go-work.XXXXXXXX")
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
(cd "$tmp" && go work init "$source_dir")
GOWORK="$tmp/go.work" go run github.com/NonLogicalDev/util.layerctl/cmd/layerctl "$@"
