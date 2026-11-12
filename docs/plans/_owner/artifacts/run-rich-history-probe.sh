#!/usr/bin/env bash
# Run the rich-history geometry probe without creating another Cargo target.
# Existing rlibs can be stale relative to the vendor tree: this script prints
# their paths and does not claim that the result validates the current source.
set -eu

root="$(git rev-parse --show-toplevel)"
tmp_dir="$(mktemp -d "${TMPDIR:-/tmp}/solidrecipe-rich-history.XXXXXX")"
trap 'rm -rf "$tmp_dir"' EXIT

for kernel in "$root"/target/debug/deps/libsolidcraft_kernel-*.rlib; do
  [[ -f "$kernel" ]] || continue
  for record in "$root"/target/debug/deps/libsolidcore_record-*.rlib; do
    [[ -f "$record" ]] || continue
    if rustc --edition=2021 "$root/docs/plans/_owner/artifacts/probe-rich-history.rs" \
      -L "dependency=$root/target/debug/deps" --extern "solidcraft_kernel=$kernel" \
      --extern "solidcore_record=$record" -o "$tmp_dir/probe" 2>"$tmp_dir/error"; then
      printf 'Using existing build artifacts (check their freshness):\n%s\n%s\n' "$kernel" "$record"
      "$tmp_dir/probe"
      exit 0
    fi
  done
done
printf 'No compatible existing SolidCraft kernel and SolidCore record rlibs found.\n' >&2
[[ ! -f "$tmp_dir/error" ]] || cat "$tmp_dir/error" >&2
exit 1
