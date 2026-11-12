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
- 2026-11-10: User requested component directories under `src/solidrecipe-core`, `src/solidrecipe-cli`, and `src/solidrecipe-viewer`; move them while preserving examples and plans at the root and update all references.
- 2026-11-10: User requested source dependencies as Git submodules in `vendor/`. Vendor SolidCore, update Cargo paths, and retain registry package management for Python and JavaScript.
- 2026-11-10: Implemented initial CLI server, file watcher, and R3F polling. Strict format and lint checks pass. End-to-end live update and failure recovery are not yet verified.
- 2026-11-10: Browser confirmed the initial preview and automatic geometry update after a file edit. A failed rebuild retains the previous model; make the error fully readable and verify recovery. User also requested consistently dense documentation and inline comments.
- 2026-11-10: User requires the compiled CLI to run from any working directory. Embed built viewer assets and the Python runtime modules in the binary; test outside the checkout. Python model execution still requires an available Python interpreter and uv.

- 2026-11-10: Implemented CLI `serve` with an embedded R3F viewer and Python support, loopback server, automatic regeneration, readable failure reporting, and last-good preview. A copied binary ran from `/tmp`; updates and error recovery were observed in the browser. Verified restrictive temporary permissions and cleanup on Ctrl+C. `make check` passed: formatting, Clippy, Ruff, Biome, Rust tests, Python integration tests, and viewer build. Remaining limitations: `uv` and Python are required; only the selected model file is watched; exact measurement and CAD exchange are not implemented.
