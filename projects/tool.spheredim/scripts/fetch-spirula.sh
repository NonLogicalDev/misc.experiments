#!/bin/sh
# Fetch a pinned release without committing its binary to the repository.
set -eu
if [ "$#" -ne 1 ]; then echo "Usage: $0 OUTPUT_DIRECTORY" >&2; exit 2; fi
case "$(uname -s)-$(uname -m)" in
  Darwin-arm64) asset=spirula-2026.11.12-macos-vulkan-arm64.dmg; digest=e7da3c65342178a876ad0dc7e0ab72afcab20479d7ba95c52f8ca8308019a540 ;;
  Linux-x86_64) asset=spirula-2026.11.12-ubuntu-vulkan-x86_64.zip; digest=07afb39882f336555633a17023a18c52502dcf0a18b23fe62fa5dd1c24b19a93 ;;
  *) echo 'No pinned release for this platform.' >&2; exit 1 ;;
esac
mkdir -p "$1"
dest="$1/$asset"
if [ -e "$dest" ]; then echo "Output already exists: $dest" >&2; exit 1; fi
tmp=$(mktemp "$1/.spirula-download.XXXXXXXX")
trap 'rm -f "$tmp"' EXIT HUP INT TERM
curl --fail --location --output "$tmp" "https://github.com/harry7557558/spirula-studio/releases/download/v2026.11.12/$asset"
if command -v sha256sum >/dev/null 2>&1; then actual=$(sha256sum "$tmp" | cut -d ' ' -f 1); else actual=$(shasum -a 256 "$tmp" | cut -d ' ' -f 1); fi
if [ "$actual" != "$digest" ]; then echo 'SHA-256 mismatch; download discarded.' >&2; exit 1; fi
mv "$tmp" "$dest"
trap - EXIT HUP INT TERM
printf 'Verified: %s\n' "$dest"
