# Architecture

SolidRecipe is a code-driven CAD experiment. Embedded Python executes a model file and builds a graph; the Rust core evaluates that graph through SolidCore into B-rep geometry. The Rust CLI tessellates it for a React Three Fiber viewer. Display meshes are not authoritative for CAD measurements.

## Live preview

The Rust CLI owns the loopback HTTP server, watching, parameter state, presets, graph evaluation and tessellation. Python model source runs inside the same process through PyO3; no interpreter or geometry subprocess is launched per rebuild. Models execute with the user's permissions. A Python error or Rust operation failure leaves the last successful mesh visible. Because execution is in-process, a nonterminating model or native crash cannot be forcibly isolated or timed out as a subprocess could.

The watcher tracks the exact content of the top-level file and files explicitly loaded by `sr.load`, including missing files so creation can recover an error. Ordinary Python imports are not watched. Graph subtree results are cached in memory; unchanged subtrees reuse copied B-reps, and the cache retains only nodes reachable from the last successful graph. Cache keys represent graph equivalence, not persistent topology names.

The HTTP server binds loopback only, checks Host and Origin on writes, bounds JSON request bodies, and serves only files inside the extracted viewer assets. Named presets are JSON sidecars next to the model, written atomically when the user saves. They hold output names and parameter values rather than geometry. Earlier value-only presets are still readable by the viewer.

## Build and resources

The viewer is built with pnpm and Vite before Cargo compiles the CLI. Cargo embeds those assets and Python frontend source. `make build` builds an optimized binary; `make check` verifies the debug build and tests. Python is dynamically linked, so the shared library and standard library for the build's Python version must exist at runtime. In this checkout on macOS the binary currently links to Homebrew Python 3.14. Relocatable or bundled Python distribution remains future work.

## Modules, parameters and inspection

`sr.module` groups file-local exports. `sr.export` exposes shapes or functions, while `sr.exportf` decorates function exports. `sr.load` evaluates another file in its own export scope, returning namespaced values. A preview may choose an exported shape or call a function with defaulted, named arguments. `typing.Annotated` with `sr.Param` supplies viewer metadata. Parameters and named presets apply to the selected output.

`sr.inspect` calls an in-process Rust B-rep bridge and emits JSONL on stderr. Author metadata remains on graph nodes. Face and edge indices in inspection output are temporary. Explicitly named box primitives have semantic face and edge identities that survive checked translation and scaling; Boolean and blend provenance is not yet tracked. See [feature tracking](feature-tracking.md) for the boundary. The graph supports translation, scaling, and kernel fillet/chamfer operations; blend edges currently use geometric point selection, not persistent identities. CAD-exact viewer selection, STEP exchange, general topology identity, and a cross-language plugin protocol remain future work.
