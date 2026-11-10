# solidrecipe

A small experiment in code-driven CAD with SolidCore as its B-rep kernel. Python builds an expression graph; a Rust evaluator constructs the solids, computes volume, and tessellates the result for a standalone browser preview. The mesh is for display only and cannot provide exact B-rep measurements.

The initial example is a synthetic slotted block, not a verified cooler adapter.

## Build and run

Install Rust, `uv`, pnpm, Node.js, and Python. Initialize the SolidCore submodule and install the viewer dependencies, then build the embedded viewer and CLI:

```sh
git submodule update --init --recursive
pnpm -C src/solidrecipe-viewer install
make build
./target/debug/solidrecipe serve examples/slotted_block.py
```

The CLI opens a loopback viewer and rebuilds when the specified Python file changes. A model file defines a `solidrecipe` shape named `model`; see the example. If a rebuild fails, the previous preview remains visible and the error appears in the viewer. Only the selected file is watched; changes to imported modules do not trigger a rebuild. Model files run as Python code with your permissions.

The compiled executable embeds the viewer and Python support modules, so it can run from any directory without the checkout. Python model execution still requires `uv` and a Python interpreter. Use `--port PORT` or `--no-browser` after the model path when needed. `Ctrl+C` stops the server.

The original headless graph-to-OBJ workflow remains available:

```sh
uv run python examples/slotted_block.py 4.6 graph.json
./target/debug/solidrecipe graph.json bracket.obj
```

Run `make format` to apply the Rust, Python and TypeScript formatters; `make format-check`, `make lint` and `make check` verify the project. See [architecture](docs/architecture.md) for the data flow and current limitations.

## Structure

- `src/solidrecipe-core/`: graph evaluation, SolidCore geometry, display tessellation, and the experimental Python authoring interface.
- `src/solidrecipe-cli/`: headless graph evaluation and OBJ output.
- `src/solidrecipe-viewer/`: React and TypeScript web UI with a React Three Fiber OBJ mesh viewer.
- `examples/`: runnable model examples.

## Scope

Box primitives and Boolean union, subtraction and intersection are implemented. The viewer does not support exact selection or measurements. STEP import/export, fillets, watching imported files, a persistent B-rep and a stable API are not implemented. Geometry has not been validated for manufacturing.

## Direction

The goal is a modern, code-driven CAD experience in the spirit of OpenSCAD: edit a model as code, change parameters, and inspect the result interactively. Modeling code and its dependency graph should remain first-class, rather than requiring a GUI feature timeline as the source of truth.

The modeling core and viewer should support more than one scripting or API language. Python is the first interface. SolidCore is the initial B-rep kernel under evaluation. The prototype's JSON expression graph is a starting experiment, not a settled plugin protocol or a complete product architecture.

The intended experience includes a responsive preview, useful parameter controls, and CAD inspection and exchange capabilities. Backend-independent topology identity, exact measurements, file exchange, language plugin contracts, and the editor integration remain design and validation work.

### File-first and agent-first

- The project and its model source live in ordinary local files. A human or an agent can read and edit them with standard tools; the application must not require a hidden database or cloud service as the authoritative copy.
- Agent workflows are a primary interface, alongside the human editor. Provide documented, scriptable operations to evaluate models, inspect results and errors, and export artifacts without driving the GUI.
- The interactive editor and headless interfaces should share the same modeling behavior and report failures clearly. The exact command and plugin protocols remain to be designed.
