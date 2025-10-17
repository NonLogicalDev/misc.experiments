#!/bin/bash
# Universal script to run solution with optional input file

set -euo pipefail

SOLUTION_BINARY="$1"

# Check if input.txt exists in the current directory
if [ -f "input.txt" ]; then
    echo "Running with input.txt"
    "$SOLUTION_BINARY" < input.txt
else
    echo "No input.txt found, running normally"
    "$SOLUTION_BINARY"
fi