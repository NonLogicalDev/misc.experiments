#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
tmp=$(mktemp -d "${TMPDIR:-/tmp}/spheredim-layerctl.XXXXXXXX")
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
tar -xzf "$root/vendor/360dvo-46f5ed0.git.tar.gz" -C "$tmp"
n=${GIT_CONFIG_COUNT:-0}
cd "$root"
env "GIT_CONFIG_COUNT=$((n + 1))" \
  "GIT_CONFIG_KEY_${n}=url.$tmp/upstream.git.insteadOf" \
  "GIT_CONFIG_VALUE_${n}=https://github.com/chris1004336379/360DVO.git" \
  "${LAYERCTL_BIN:-layerctl}" "$@"
