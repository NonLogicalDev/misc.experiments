# Architecture

Solidrecipe is a code-driven CAD experiment. A model is an ordinary Python file that defines `model` as a `solidrecipe.Shape`. Python creates a graph; the Rust core evaluates that graph through SolidCore into a B-rep. The CLI asks the core for a tessellated display mesh. The viewer renders that mesh, which is not authoritative for exact CAD measurements.

## Live preview

`solidrecipe serve model.py` extracts its embedded viewer and Python support modules into a private temporary directory. It starts a local preview server through `uv` and opens the browser. The server hashes the selected model file, evaluates a changed file in a separate Python process, and invokes the CLI to generate the mesh. Only a successful rebuild advances the preview revision. On failure, the browser keeps the previous mesh and shows the error; fixing the model triggers another attempt.

The server listens only on loopback. It serves the extracted viewer and a read-only preview endpoint; it rejects other hostnames and paths outside the asset directory. It executes the selected Python file with the user's permissions. Use only model files you trust. The watcher currently monitors the selected file only; changes to imported helper modules do not trigger a rebuild.

## Build and resources

The viewer is built with pnpm and Vite before Cargo compiles the CLI. Cargo embeds the resulting assets and the Python frontend and runtime. `make build` enforces that order. The resulting binary does not need a project checkout at runtime, though running Python models requires `uv` and a Python interpreter on the machine.

The web UI uses React Three Fiber and Drei controls on top of Three.js. It renders on demand and fetches preview revisions from the local server. CAD-exact selection, measurements, STEP exchange, language plugins, and general dependency tracking remain future work.
