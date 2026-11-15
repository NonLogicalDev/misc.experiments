#!/bin/sh
# Compose the pinned SolidCraft tree without modifying its source submodule.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
source_dir="$root/vendor/solidcraft"
state="$root/.solidcraft-layerctl"
definitions="$state/definitions"
workspace="$state/workspace"
revision=9e805b7bdc843eeae419c7008561f829348acb57
fail() { printf '%s\n' "solidcraft preparation: $*" >&2; exit 1; }
command -v layerctl >/dev/null 2>&1 || fail 'install layerctl: https://github.com/NonLogicalDev/util.layerctl'
[ -e "$source_dir/.git" ] || fail 'initialize submodules first: git submodule update --init --recursive'
[ "$(git -C "$source_dir" rev-parse HEAD)" = "$revision" ] || fail 'SolidCraft revision differs from the pinned revision'
patches='solidcore-ordered-provenance.patch solidcore-stitch-notifications.patch solidcore-attribute-audit.patch solidcore-slit-notifications.patch solidcore-triangle-edge-map.patch'
check_source() {
    # A clean source and the previously prepared source are both valid. Never
    # silently ignore a developer's additional changes in the old submodule.
    untracked=$(git -C "$source_dir" ls-files --others --exclude-standard)
    [ -z "$untracked" ] || fail "source contains untracked files: $source_dir"
    source_diff=$(git -C "$source_dir" diff --binary HEAD)
    expected_diff=$(git -C "$workspace" diff --binary "$revision" HEAD)
    [ -z "$source_diff" ] || [ "$source_diff" = "$expected_diff" ] || fail "source contains unexpected changes: $source_dir"
}
inputs=$(git hash-object "$0" "$root"/patches/vendor/solidcore-ordered-provenance.patch "$root"/patches/vendor/solidcore-stitch-notifications.patch "$root"/patches/vendor/solidcore-attribute-audit.patch "$root"/patches/vendor/solidcore-slit-notifications.patch "$root"/patches/vendor/solidcore-triangle-edge-map.patch)
if [ -e "$state" ]; then
    [ -f "$state/inputs" ] && [ "$(cat "$state/inputs")" = "$inputs" ] || fail "preparation inputs changed or setup is incomplete; preserve any work in $state, then remove it and rebuild"
    [ -f "$state/head" ] && [ -d "$workspace" ] || fail "incomplete setup at $state; preserve any work there before removing it and retrying"
    for patch in $patches; do
        cmp -s "$root/patches/vendor/$patch" "$definitions/layers/0002-solidrecipe/$patch" || fail "patches changed; preserve any work in $state, then remove it and rebuild"
    done
    [ "$(git -C "$workspace" rev-parse HEAD)" = "$(cat "$state/head")" ] || fail "workspace HEAD changed: $workspace"
    [ -z "$(git -C "$workspace" status --porcelain --untracked-files=normal)" ] || fail "workspace contains changes: $workspace"
    check_source
    exit 0
fi
mkdir -p "$definitions/layers/0001-solidcraft" "$definitions/layers/0002-solidrecipe"
git -C "$definitions" init -q
# JSON string syntax is valid TOML for a filesystem path and handles spaces.
source_url=$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1]))' "$source_dir")
cat > "$definitions/layers/0001-solidcraft/layer.toml" <<MANIFEST
[layer]
enabled = true
[vcs]
commit-msg = "Import SolidCraft"
[[operation]]
[operation.git-clone]
url = $source_url
commit = "$revision"
depth = 1
MANIFEST
cat > "$definitions/layers/0002-solidrecipe/layer.toml" <<'MANIFEST'
[layer]
enabled = true
[vcs]
commit-msg = "Apply SolidRecipe patches"
MANIFEST
for patch in $patches; do
    cp "$root/patches/vendor/$patch" "$definitions/layers/0002-solidrecipe/$patch"
    printf '\n[[operation]]\n[operation.patch]\nfile = "%s"\n' "$patch" >> "$definitions/layers/0002-solidrecipe/layer.toml"
done
(cd "$definitions" && layerctl projection create solidcraft --worktree "$workspace")
check_source
git -C "$workspace" rev-parse HEAD > "$state/head"
printf '%s\n' "$inputs" > "$state/inputs"
