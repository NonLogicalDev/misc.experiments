#!/bin/sh
set -eu
# Run from the integration definition directory; preserve caller arguments and cwd.
command -v go >/dev/null || { echo 'Go 1.26 or newer is required on PATH.' >&2; exit 1; }
exec go run github.com/NonLogicalDev/util.layerctl/cmd/layerctl@042f26dbca7bc47a95fad5c1e88a696e52a1409a "$@"
