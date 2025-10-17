#!/usr/bin/env bash

set -euo pipefail

# VS Code commit to pull types from
VSCODE_COMMIT="${VSCODE_COMMIT:-1e1dabdbb9edc1df2fcf34fde86264a7d3a8a690}"

# Function to download a file from VS Code repository
# Usage: vscode_file_pull <destination> <source-path-relative-to-vscode-root>
vscode_file_pull() {
    local dst="$1"
    local src="$2"
    local url="https://raw.githubusercontent.com/microsoft/vscode/${VSCODE_COMMIT}/${src}"
    
    echo "  - Downloading $(basename "${dst}")..."
    curl -L -o "${dst}" "${url}"
}

main() {
    # Source directory (defaults to 'src')
    SRC_DIR="${1:-src}"
    TYPES_DIR="${SRC_DIR}/types/external"

    # Ensure the types/external directory exists
    mkdir -p "${TYPES_DIR}"

    echo "Downloading TypeScript definitions from VS Code commit: ${VSCODE_COMMIT}"
    echo "Target directory: ${TYPES_DIR}"

    # Download TypeScript definitions
    # Note: vscode.d.ts is provided by @types/vscode package, so we only download:
    # 1. Git extension API (not in @types/vscode)
    # 2. Proposed SCM History Provider API (not yet in stable @types/vscode)
    vscode_file_pull "${TYPES_DIR}/vscode.ext__git.d.ts" "extensions/git/src/api/git.d.ts"
    vscode_file_pull "${TYPES_DIR}/vscode.dts__vscode.proposed.scmHistoryProvider.d.ts" "src/vscode-dts/vscode.proposed.scmHistoryProvider.d.ts"

    echo "✓ TypeScript definitions updated successfully"
}

main "$@"