# Architecture

Solidrecipe is a code-driven CAD experiment. A model is an ordinary Python file that defines `model` as a `solidrecipe.Shape`. Python creates a graph; the Rust core evaluates that graph through SolidCore into a B-rep. The CLI asks the core for a tessellated display mesh. The viewer renders that mesh, which is not authoritative for exact CAD measurements.

## Live preview

`solidrecipe serve model.py` extracts its embedded viewer and Python support modules into a private temporary directory. It starts a local preview server through `uv` and opens the browser. The server hashes the selected model file, evaluates a changed file in a separate Python process, and invokes the CLI to generate the mesh. Only a successful rebuild advances the preview revision. On failure, the browser keeps the previous mesh and shows the error; fixing the model triggers another attempt.

The server listens only on loopback. It serves the extracted viewer and a read-only preview endpoint; it rejects other hostnames and paths outside the asset directory. It executes the selected Python file with the user's permissions. Use only model files you trust. The watcher currently monitors the selected file only; changes to imported helper modules do not trigger a rebuild.

## Build and resources

The viewer is built with pnpm and Vite before Cargo compiles the CLI. Cargo embeds the resulting assets and the Python frontend and runtime. `make build` enforces that order. The resulting binary does not need a project checkout at runtime, though running Python models requires `uv` and a Python interpreter on the machine.

The web UI uses React Three Fiber and Drei controls on top of Three.js. It renders on demand and fetches preview revisions from the local server. CAD-exact selection, measurements, STEP exchange, language plugins, and general dependency tracking remain future work.

## Parameters and presets

A Python model declares parameters with `sr.parameter`. The evaluation subprocess records each declaration and applies the preview server's current overrides. The server publishes those declarations alongside the successful preview; failed evaluations retain the last good mesh and expose their error. A parameter update schedules a rebuild without editing the source model.

Named presets are JSON sidecars next to the model, written atomically only when the user saves. They hold parameter values rather than geometry, so model validation still runs when a preset is loaded. The preview server accepts JSON writes only from its own loopback origin and limits request size. Imported helper files are still not watched.

`sr.inspect` evaluates its shape through the CLI and emits one JSON record per call on stderr. Successful preview evaluations forward those records to the terminal. Shape-node metadata is preserved in the graph; B-rep entity indices are temporary. See [feature tracking](feature-tracking.md) for the kernel's current provenance boundary.
