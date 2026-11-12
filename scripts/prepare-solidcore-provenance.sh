#!/bin/sh
# Apply only the versioned patches to the exact, otherwise untouched dependency.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
vendor="$root/vendor/solidcraft"
provenance=solidcore/crates/solidcore-ops/src/provenance.rs
attribute=solidcore/crates/solidcore/src/geom/attribute.rs
stitch_one=solidcore/crates/solidcore/src/heal/stitch/p1.rs
stitch_two=solidcore/crates/solidcore/src/heal/stitch/p2.rs
provenance_patch="$root/patches/vendor/solidcore-ordered-provenance.patch"
stitch_patch="$root/patches/vendor/solidcore-stitch-notifications.patch"
audit_patch="$root/patches/vendor/solidcore-attribute-audit.patch"
revision=9e805b7bdc843eeae419c7008561f829348acb57
fail() { printf '%s\n' "solidcore preparation: $*" >&2; exit 1; }
[ -e "$vendor/.git" ] || fail "initialize submodules first: git submodule update --init --recursive"
[ "$(git -C "$vendor" rev-parse HEAD)" = "$revision" ] || fail "SolidCraft revision differs from the pinned revision"
status=$(git -C "$vendor" status --porcelain --untracked-files=normal)
old_provenance=22342828da0d27ea46164136695778f63b02be6a
new_provenance=f374d1e13aec04f8bfa488fc6c61be5c9a9bf3de
audited_provenance=20ba647f92efae5736858c360a92a564fd030f65
old_attribute=ad6b9175e06f0f28285c7e8a6937ef0f83b09fdf
new_attribute=5f4095152e0c9628193496d2d0c39744fab09790
old_one=5a148d31f59ccffe6ac9908caa69388790a6d38f
new_one=7c358aa7329e8e756514edd1d0f3c0dda905aa8d
old_two=4255ea4836b58e5005f1d800dd3688f424664ff7
new_two=323ff9530f123e82c8bccaa5afded4f16f4193ce
prov_blob=$(git -C "$vendor" hash-object "$provenance")
attribute_blob=$(git -C "$vendor" hash-object "$attribute")
one_blob=$(git -C "$vendor" hash-object "$stitch_one")
two_blob=$(git -C "$vendor" hash-object "$stitch_two")
previous=$(printf ' M %s' "$provenance")
prior_complete=$(printf ' M %s\n M %s\n M %s' "$provenance" "$stitch_one" "$stitch_two")
complete=$(printf ' M %s\n M %s\n M %s\n M %s' "$provenance" "$attribute" "$stitch_one" "$stitch_two")
if [ "$status" = "$complete" ] && [ "$prov_blob" = "$audited_provenance" ] && [ "$attribute_blob" = "$new_attribute" ] && [ "$one_blob" = "$new_one" ] && [ "$two_blob" = "$new_two" ]; then
    exit 0
fi
# A checkout prepared by an earlier SolidRecipe version is the only accepted
# partial state. Any other local edit is preserved and rejected.
if [ -z "$status" ] && [ "$prov_blob" = "$old_provenance" ] && [ "$attribute_blob" = "$old_attribute" ] && [ "$one_blob" = "$old_one" ] && [ "$two_blob" = "$old_two" ]; then
    git -C "$vendor" apply --check "$provenance_patch" || fail "provenance patch does not match the pinned source"
    git -C "$vendor" apply --check "$stitch_patch" || fail "stitch patch does not match the pinned source"
    git -C "$vendor" apply "$provenance_patch" || fail "could not apply provenance patch"
elif [ "$status" = "$prior_complete" ] && [ "$prov_blob" = "$new_provenance" ] && [ "$attribute_blob" = "$old_attribute" ] && [ "$one_blob" = "$new_one" ] && [ "$two_blob" = "$new_two" ]; then
    git -C "$vendor" apply --check "$audit_patch" || fail "attribute audit patch does not match the pinned source"
    git -C "$vendor" apply "$audit_patch" || fail "could not apply attribute audit patch"
    [ "$(git -C "$vendor" hash-object "$provenance")" = "$audited_provenance" ] && [ "$(git -C "$vendor" hash-object "$attribute")" = "$new_attribute" ] || fail "patched files have unexpected hashes"
    exit 0
elif [ "$status" != "$previous" ] || [ "$prov_blob" != "$new_provenance" ] || [ "$attribute_blob" != "$old_attribute" ] || [ "$one_blob" != "$old_one" ] || [ "$two_blob" != "$old_two" ]; then
    fail "SolidCraft contains unexpected changes; preserve them and resolve the mismatch before applying the patches"
fi
git -C "$vendor" apply --check "$stitch_patch" || fail "stitch patch does not match the pinned source"
git -C "$vendor" apply "$stitch_patch" || fail "could not apply stitch patch"
git -C "$vendor" apply --check "$audit_patch" || fail "attribute audit patch does not match the pinned source"
git -C "$vendor" apply "$audit_patch" || fail "could not apply attribute audit patch"
[ "$(git -C "$vendor" hash-object "$provenance")" = "$audited_provenance" ] && [ "$(git -C "$vendor" hash-object "$attribute")" = "$new_attribute" ] && [ "$(git -C "$vendor" hash-object "$stitch_one")" = "$new_one" ] && [ "$(git -C "$vendor" hash-object "$stitch_two")" = "$new_two" ] || fail "patched files have unexpected hashes"
