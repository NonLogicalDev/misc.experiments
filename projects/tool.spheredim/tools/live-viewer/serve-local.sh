#!/bin/sh
# Supply a viewer state JSON; relative paths in it resolve beside that file.
set -eu
viewer_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$viewer_dir"
: "${SPHEREDIM_STATE:?Set SPHEREDIM_STATE to the viewer state JSON file}"
exec "${SPHEREDIM_NODE:-node}" ./node_modules/vite/bin/vite.js
