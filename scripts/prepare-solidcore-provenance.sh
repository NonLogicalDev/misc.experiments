#!/bin/sh
# Apply the versioned project patch only to the exact, otherwise untouched dependency.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
vendor="$root/vendor/solidcraft"
file=solidcore/crates/solidcore-ops/src/provenance.rs
patch="$root/patches/vendor/solidcore-ordered-provenance.patch"
revision=9e805b7bdc843eeae419c7008561f829348acb57
original=22342828da0d27ea46164136695778f63b02be6a
patched=f374d1e13aec04f8bfa488fc6c61be5c9a9bf3de
fail() { printf '%s\n' "solidcore preparation: $*" >&2; exit 1; }
[ -e "$vendor/.git" ] || fail "initialize submodules first: git submodule update --init --recursive"
[ "$(git -C "$vendor" rev-parse HEAD)" = "$revision" ] || fail "SolidCraft revision differs from the pinned revision"
status=$(git -C "$vendor" status --porcelain --untracked-files=normal)
blob=$(git -C "$vendor" hash-object "$file")
if [ "$status" = " M $file" ] && [ "$blob" = "$patched" ]; then
    exit 0
fi
[ -z "$status" ] && [ "$blob" = "$original" ] || fail "SolidCraft contains unexpected changes; preserve them and resolve the mismatch before applying the patch"
git -C "$vendor" apply --check "$patch" || fail "patch does not match the pinned source"
git -C "$vendor" apply "$patch" || fail "could not apply patch"
[ "$(git -C "$vendor" hash-object "$file")" = "$patched" ] || fail "patched file has an unexpected hash"
