# solidrecipe

A small experiment in code-driven CAD with SolidCore as its B-rep kernel. Python builds an expression graph; a Rust evaluator constructs the solids, computes volume, and tessellates the result for a standalone browser preview. The mesh is for display only and cannot provide exact B-rep measurements.

The initial example is a synthetic slotted block, not a verified cooler adapter.

## Run

The prototype requires Rust, `uv`, pnpm, Node.js, and a SolidCore checkout at `../../../remote/github.com/tangency-labs/solidcore` relative to this project. It was developed against SolidCore commit `ecd20d47c8e6a83fd7531da76f1cb3b7c7c74d34`; its API is experimental.

```sh
cargo build
uv run python examples/slotted_block.py 4.6 graph.json
cargo run -p solidrecipe -- graph.json bracket.obj
cd viewer
pnpm install
pnpm dev
```

Open the local address printed by Vite, then use **Open OBJ** to select `bracket.obj`. Drag to orbit, right-drag to pan, and scroll to zoom. After changing the example, regenerate the graph and OBJ and open it again. The viewer currently reads a user-selected mesh; it does not watch files or run the model.

## Structure

- `core/`: graph evaluation, SolidCore geometry, display tessellation, and the experimental Python authoring interface.
- `cli/`: headless graph evaluation and OBJ output.
- `viewer/`: React and TypeScript web UI with a Three.js OBJ mesh viewer.
- `examples/`: runnable model examples.

## Scope

Box primitives and Boolean union, subtraction and intersection are implemented. The viewer does not support exact selection or measurements. STEP import/export, fillets, live reload, a persistent B-rep and a stable API are not implemented. Geometry has not been validated for manufacturing.

## Direction

The goal is a modern, code-driven CAD experience in the spirit of OpenSCAD: edit a model as code, change parameters, and inspect the result interactively. Modeling code and its dependency graph should remain first-class, rather than requiring a GUI feature timeline as the source of truth.

The modeling core and viewer should support more than one scripting or API language. Python is the first interface. SolidCore is the initial B-rep kernel under evaluation. The prototype's JSON expression graph is a starting experiment, not a settled plugin protocol or a complete product architecture.

The intended experience includes a responsive preview, useful parameter controls, and CAD inspection and exchange capabilities. Backend-independent topology identity, exact measurements, file exchange, language plugin contracts, and the editor integration remain design and validation work.

### File-first and agent-first

- The project and its model source live in ordinary local files. A human or an agent can read and edit them with standard tools; the application must not require a hidden database or cloud service as the authoritative copy.
- Agent workflows are a primary interface, alongside the human editor. Provide documented, scriptable operations to evaluate models, inspect results and errors, and export artifacts without driving the GUI.
- The interactive editor and headless interfaces should share the same modeling behavior and report failures clearly. The exact command and plugin protocols remain to be designed.
