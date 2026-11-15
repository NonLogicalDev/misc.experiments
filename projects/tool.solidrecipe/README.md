# solidrecipe

A small experiment in code-driven CAD with SolidCore as its B-rep kernel. Embedded Python builds an expression graph; Rust evaluates the solids and tessellates them for a browser preview. The mesh is for display only and cannot provide exact B-rep measurements.

The initial example is a synthetic slotted block, not a verified cooler adapter.

## Build and run

Install Rust, `uv`, pnpm, Node.js, Python, and [layerctl](https://github.com/NonLogicalDev/util.layerctl). Configure a Git author and committer identity. Initialize the vendor submodules and install the viewer dependencies, then build the embedded viewer and optimized CLI (the first build can take a few minutes):

```sh
git submodule update --init --recursive
pnpm -C src/solidrecipe-viewer install
make build
./target/release/solidrecipe serve examples/slotted_block.py
```

`make build`, `make lint`, and `make check` use layerctl to compose the pinned SolidCraft submodule and the five patches in `patches/vendor/` into `.solidcraft-layerctl/workspace`. The source submodule is not modified. Before invoking Cargo directly, run `make prepare-solidcore`. Preparation rejects unexpected source-submodule edits and refuses to replace a changed, stale, or incomplete workspace. To rebuild it, first preserve any work in `.solidcraft-layerctl/`, then remove that directory and run `make prepare-solidcore` again.

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

Box and cylinder primitives, Boolean operations, translation, scaling, fillets and chamfers are implemented. Blend edges are selected by model-space points or supported experimental references. The viewer supports inspecting and selecting topology, but selection uses display geometry rather than exact geometric picking. STEP import/export, watching ordinary Python imports, a persistent B-rep and a stable API are not implemented. Geometry has not been validated for manufacturing.

## Direction

The goal is a modern, code-driven CAD experience in the spirit of OpenSCAD: edit a model as code, change parameters, and inspect the result interactively. Modeling code and its dependency graph should remain first-class, rather than requiring a GUI feature timeline as the source of truth.

The modeling core and viewer should support more than one scripting or API language. Python is the first interface. SolidCore is the initial B-rep kernel under evaluation. The prototype's JSON expression graph is a starting experiment, not a settled plugin protocol or a complete product architecture.

The intended experience includes a responsive preview, useful parameter controls, and CAD inspection and exchange capabilities. Backend-independent topology identity, exact measurements, file exchange, language plugin contracts, and the editor integration remain design and validation work.

### File-first and agent-first

- The project and its model source live in ordinary local files. A human or an agent can read and edit them with standard tools; the application must not require a hidden database or cloud service as the authoritative copy.
- Agent workflows are a primary interface, alongside the human editor. Provide documented, scriptable operations to evaluate models, inspect results and errors, and export artifacts without driving the GUI.
- The interactive editor and headless interfaces should share the same modeling behavior and report failures clearly. The exact command and plugin protocols remain to be designed.

### Cooler adapter experiment

`examples/cooler_adapter.py` reconstructs the main dimensions of either NH-L12S adapter in SolidRecipe. Use the viewer parameters to inspect the left or right half and the 4.5, 4.6, or 4.7 mm slot. It is a development comparison, not a manufacturing model: the 0.5 mm ledge fillet, outer rounds, and recessed labels are not yet reproduced; 2 mm slot-entry fillets and a 1 mm underside chamfer are included. The authoritative submitted design remains in the separate homelab cooler adapters project.

### Inspecting a shape

Call `sr.inspect(model, name="bracket")` in a model to write one JSON object per call to stderr. In a live preview, records appear in the CLI's terminal. A record includes the construction graph, node metadata, B-rep bounds and volume, face surfaces and areas, and edge curves, endpoints, lengths and adjacent faces. Face and edge indices refer only to that particular evaluated B-rep; they are not persistent references.

Use `shape.with_metadata(name="stock", role="bracket")` to attach JSON-serializable author metadata to a graph node. Metadata stays with that node in the graph; it is not yet tracked onto resulting B-rep faces or edges. Inspection requires SolidRecipe’s embedded runtime; it does not start another process.

### Selecting topology in the viewer

Run `./target/release/solidrecipe serve examples/cooler_adapter.py` to open the adapter, or replace the path with another model. Choose **Edges** or **Faces**, then click the displayed geometry to add or remove entries from the selection. You can select multiple edges and faces, switch modes, and use **Clear** to remove the selection. The viewer also displays selection sent through its local preview API.

Use **Copy for Python** to copy the selection with its model, output, applied parameters and evaluated revision. Selected entries include revision-scoped indices and hashes of their inspection records. These hashes help identify the displayed records; neither the hashes nor the indices are persistent topology identities. A successful rebuild clears the selection, because the new body can have different indices. Display geometry determines where a click lands; use the B-rep inspection data for measurements.

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

### Sketch regions and extrusion

Sketch curves can intersect to form multiple closed regions. Select a region by a point inside it, then extrude it into a solid:

```python
outline = sr.Polygon([(0, 0), (20, 0), (20, 10), (0, 10)])
divider = sr.Line((0, 5), (20, 5))
sketch = sr.Sketch([*outline, divider])
upper = sketch.profile_at((10, 7)).extrude(3)

# Add a parallel curve; positive distance is left of its direction.
offset_sketch = sketch.offset([divider], 2)
strip = offset_sketch.profile_at((10, 6)).extrude(3)
sr.export("strip", strip)
```

Curves include `Line`, circular `Arc`, `CubicBezier`, and the segment lists returned by `Polygon`, `Circle`, and `CatmullRom`. `Sketch.offset` accepts an ordered chain of existing curves, preserves the originals, and recomputes the offset as part of the graph. It uses the sketch engine's offset algorithm and may reject difficult or degenerate inputs. Duplicate identical source curves are ambiguous. `Sketch` and `Profile` accept `plane="XY"`, `"XZ"`, `"YZ"`, or an explicit orthonormal frame. `Profile` also accepts an explicitly ordered outer loop and holes.

Place a sketch in 3D with a plane. Supply any two perpendicular unit directions; the third follows the right-hand rule. Z is the extrusion direction:

```python
plane = sr.Plane(origin=(10, 0, 5), x_dir=(0, 1, 0), z_dir=(1, 0, 0))
sketch = sr.Sketch(outline, plane=plane)
solid = sketch.profile_at((10, 7.5)).extrude(3)  # extends along world +X
```

Point selection is a geometric query, not a persistent region identity: after an edit, the same point may select a different region. The sketch engine samples outlines for containment, so choose points well away from boundaries. Generated extrusion faces do not yet have persistent identities. Constraints, face-attached sketches, and sweeps along paths remain future work.

### Part placement and edge blends

Shapes are immutable-style graph nodes: build a part in local coordinates, then place or scale it without changing the source shape. Scaling is about the origin and accepts one uniform factor or three axis factors.

```python
part = sr.Box(10, 20, 5)
placed = part.scale(1.2).translate(30, 0, 0)
rounded = part.fillet(edge_points=[[0, 0, 2.5]], radius=1)
beveled = part.chamfer(edge_points=[[0, 0, 2.5]], distance=1)
```

Blend points are in the input body's coordinates, in millimeters. Each must match exactly one edge within the specified tolerance, which defaults to 0.01 mm. These selections are geometric, not persistent feature identities; changes to the model can cause them to fail or select a different edge, so inspect and verify important geometry.

### Measurements and initial topology identities

Earlier shapes can drive later calculations in the embedded runtime:

```python
stock = sr.Box(10, 20, 5).with_metadata(id="stock")
measurements = stock.measure()
length = measurements.bounds.size[0]
edge = stock.edge("x_min", "y_min")
placed = stock.translate(30, 0, 0)
same_edge = placed.resolve(edge["identity"])
```

Measurements evaluate the B-rep in-process. Bounds use millimeters and volume uses cubic millimeters; `.bounds` exposes `minimum`, `maximum`, `size`, and `center`. `sr.inspect_data(shape)` returns detailed B-rep data as a Python value, while `sr.inspect(shape)` prints JSONL.

Named-box face and edge identities can propagate through transforms, Boolean operations, and blends. A unique surviving edge can also select a blend: `placed.fillet(edge_refs=[edge["identity"]], radius=1)`. Named instances distinguish repeated parts. This support is experimental: kernel provenance is not yet proven complete for every operation, and generated topology does not have stable identities. Missing, split, merged, or ambiguous references raise an error rather than selecting a nearby edge. See [feature tracking](docs/feature-tracking.md).
