# Connect CLI and live viewer

## Purpose

Run the viewer from the CLI for a specific local Python model, and automatically regenerate its preview when that model file changes.

## Scope

- Run a local server bound to loopback and serve the built viewer and the selected model's latest preview.
- Generate the graph from the selected Python file using the project Python environment, evaluate it using the existing SolidCore core, and deliver the display mesh to the browser.
- Detect edits to the selected file and regenerate; retain the last valid preview and report errors on failure.
- Preserve manual OBJ loading and CAD versus display-mesh boundaries.
- Validate startup, successful refresh, failure and recovery, and browser interaction.

## Work log

- 2026-11-10: User requested the CLI-managed live viewer during the React Three Fiber migration. Python model files are the initial supported input; the current prototype's schema and interface remain experimental.
