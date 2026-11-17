#!/bin/sh
# Compose the checked-in layerctl definitions against the pinned upstream.
set -eu
root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
layers="$root/vendor/solidcraft/layers"
state="$root/.work/solidcraft"
definitions="$state/definitions"
workspace="$state/source"
fail() { printf '%s\n' "solidcraft preparation: $*" >&2; exit 1; }
command -v layerctl >/dev/null 2>&1 || fail 'install layerctl: https://github.com/NonLogicalDev/util.layerctl'
inputs=$(find "$layers" -type f -print | LC_ALL=C sort | while IFS= read -r file; do
    printf '%s ' "${file#"$layers"/}"
    git hash-object "$file"
done)
if [ -e "$state" ]; then
    [ -f "$state/inputs" ] && [ -f "$state/head" ] && [ -d "$workspace" ] || fail "incomplete setup at $state; preserve any work there before removing it"
    [ "$(cat "$state/inputs")" = "$inputs" ] || fail "layer definitions changed; preserve any work in $state before rebuilding"
    [ "$(git -C "$workspace" rev-parse HEAD)" = "$(cat "$state/head")" ] || fail "workspace HEAD changed: $workspace"
    [ -z "$(git -C "$workspace" status --porcelain --untracked-files=normal)" ] || fail "workspace contains changes: $workspace"
    [ -L "$definitions/layers" ] || fail "layer definitions link changed: $definitions/layers"
    [ "$(CDPATH='' cd -- "$definitions/layers" && pwd -P)" = "$(CDPATH='' cd -- "$layers" && pwd -P)" ] || fail "layer definitions link changed: $definitions/layers"
    exit 0
fi
mkdir -p "$definitions"
git -C "$definitions" init -q
# The Git root is local state; the symlink keeps layerctl's authoritative
# manifests and patches in the checked-in vendor/solidcraft directory.
ln -s ../../../vendor/solidcraft/layers "$definitions/layers"
# The upstream URL and exact revision live in the checked-in first layer.
(cd "$definitions" && layerctl projection create solidcraft --worktree "$workspace")
git -C "$workspace" rev-parse HEAD > "$state/head"
printf '%s\n' "$inputs" > "$state/inputs"
