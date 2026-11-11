# solidrecipe

A small experiment in code-driven CAD with SolidCore as its B-rep kernel. Embedded Python builds an expression graph; Rust evaluates the solids and tessellates them for a browser preview. The mesh is for display only and cannot provide exact B-rep measurements.

The initial example is a synthetic slotted block, not a verified cooler adapter.

## Build and run

Install Rust, `uv`, pnpm, Node.js, and Python. Initialize the SolidCore submodule and install the viewer dependencies, then build the embedded viewer and optimized CLI (the first build can take a few minutes):

```sh
git submodule update --init --recursive
pnpm -C src/solidrecipe-viewer install
make build
./target/release/solidrecipe serve examples/slotted_block.py
```

The CLI opens a loopback viewer and rebuilds when the selected Python file or a file loaded via `sr.load` changes. A model can call `sr.export(shape)` to provide a default output; the legacy variable `model` is also supported. If a rebuild fails, the previous preview remains visible and the error appears in the viewer. Ordinary Python imports are not watched. Model files run as Python code with your permissions.

The compiled executable embeds the viewer and Python support code, so it can run from any directory without the checkout. It dynamically links the Python shared library used at build time and needs that compatible Python installation and standard library at runtime; `uv` is only needed for project development tools. Use `--port PORT` or `--no-browser` after the model path when needed. `Ctrl+C` stops the server.

The original headless graph-to-OBJ workflow remains available:

```sh
uv run python examples/slotted_block.py 4.6 graph.json
./target/release/solidrecipe graph.json bracket.obj
```

Run `make format` to apply the Rust, Python and TypeScript formatters; `make format-check`, `make lint` and `make check` verify the project. See [architecture](docs/architecture.md) for the data flow and current limitations.

## Structure

- `src/solidrecipe-core/`: graph evaluation, SolidCore geometry, display tessellation, and the experimental Python authoring interface.
- `src/solidrecipe-cli/`: headless graph evaluation and OBJ output.
- `src/solidrecipe-viewer/`: React and TypeScript web UI with a React Three Fiber OBJ mesh viewer.
- `examples/`: runnable model examples.

## Scope

Box and cylinder primitives and Boolean union, subtraction and intersection are implemented. The viewer does not support exact selection or measurements. STEP import/export, fillets, watching imported files, a persistent B-rep and a stable API are not implemented. Geometry has not been validated for manufacturing.

## Direction

The goal is a modern, code-driven CAD experience in the spirit of OpenSCAD: edit a model as code, change parameters, and inspect the result interactively. Modeling code and its dependency graph should remain first-class, rather than requiring a GUI feature timeline as the source of truth.

The modeling core and viewer should support more than one scripting or API language. Python is the first interface. SolidCore is the initial B-rep kernel under evaluation. The prototype's JSON expression graph is a starting experiment, not a settled plugin protocol or a complete product architecture.

The intended experience includes a responsive preview, useful parameter controls, and CAD inspection and exchange capabilities. Backend-independent topology identity, exact measurements, file exchange, language plugin contracts, and the editor integration remain design and validation work.

### File-first and agent-first

- The project and its model source live in ordinary local files. A human or an agent can read and edit them with standard tools; the application must not require a hidden database or cloud service as the authoritative copy.
- Agent workflows are a primary interface, alongside the human editor. Provide documented, scriptable operations to evaluate models, inspect results and errors, and export artifacts without driving the GUI.
- The interactive editor and headless interfaces should share the same modeling behavior and report failures clearly. The exact command and plugin protocols remain to be designed.

### Cooler adapter experiment

`examples/cooler_adapter.py` reconstructs the main dimensions of either NH-L12S adapter in SolidRecipe. Use the viewer parameters to inspect the left or right half and the 4.5, 4.6, or 4.7 mm slot. It is a development comparison, not a manufacturing model: the chamfer, fillets, rounded corners, and recessed labels are not yet reproduced. The authoritative submitted design remains in the separate homelab cooler adapters project.

### Inspecting a shape

Call `sr.inspect(model, name="bracket")` in a model to write one JSON object per call to stderr. In a live preview, records appear in the CLI's terminal. A record includes the construction graph, node metadata, B-rep bounds and volume, face surfaces and areas, and edge curves, endpoints, lengths and adjacent faces. Face and edge indices refer only to that particular evaluated B-rep; they are not persistent references.

Use `shape.with_metadata(name="stock", role="bracket")` to attach JSON-serializable author metadata to a graph node. Metadata stays with that node in the graph; it is not yet tracked onto resulting B-rep faces or edges. Inspection requires SolidRecipe’s embedded runtime; it does not start another process.

### Model parameters and presets

Declare parameters in the model with `sr.parameter("slot_height", 4.6, description="Slot height", unit="mm", minimum=4.5, maximum=4.7, step=0.1, options=[4.5, 4.6, 4.7])`. Supported values are numbers, strings, and booleans. Names must be unique; options restrict the allowed values and step is an input hint. The viewer applies a set of values and keeps the last successful mesh if a rebuild fails.

Save a named preset in the viewer and load it later. Presets are written as JSON beside the source model, named `<model>.py.presets.json`. Saving an existing name replaces it. Presets contain an output name and values, not geometry, and are evaluated against the current model when loaded. Earlier value-only presets remain readable.

### Reusable modules

A file may group several reusable functions with `sr.module`. A function exported with `@sr.exportf` uses its Python name; `@sr.exportf("other_name")` gives it an explicit name. `sr.export(shape)` provides a default shape, and `sr.export("name", shape)` exposes another output. `sr.export(function)` also uses the function name.

```python
from typing import Annotated
import solidrecipe as sr

with sr.module("mounts"):
    @sr.exportf
    def bracket(height: Annotated[float, sr.Param(unit="mm", minimum=2, maximum=6, step=0.1)] = 4.6):
        return sr.Box(10, 20, height)

sr.export(bracket())
```

Another file uses `mounts = sr.load("hardware.py").mounts` and calls `mounts.bracket(height=4.5)`. Relative paths resolve from the loading file. Loading exports does not put them into the caller's preview; explicitly export the resulting shape. Cycles and duplicate names are errors. Module and export names must be Python identifiers; names also support indexing, such as `hardware["mounts"]["bracket"]`.

The viewer can select an exported factory with default arguments and presents controls for its arguments. Use `typing.Annotated[T, sr.Param(...)]` for description, unit, minimum, maximum, step, and options. For preview, arguments must be named and have defaults; factories can still be loaded and called with arguments from another model. See `examples/modules/`.
