# In-process preview and parameters

## Purpose

Keep the CLI-driven viewer responsive, expose rich model parameters and saved presets, and run Python models without launching a Python subprocess for each rebuild. [Owners](../../OWNERS.md).

## Result and validation

- The Rust CLI owns the local server, source watching, presets, rebuild orchestration and B-rep/mesh work. Python runs embedded through PyO3. Model code and `sr.inspect` do not shell out; a nonterminating or native-crashing model shares the host process.
- The viewer selects exported shapes and module functions, presents `sr.parameter` and annotated `sr.Param` controls, and saves named output-aware JSON presets beside the model. Earlier value-only presets remain readable. The server restricts writes to its loopback origin and bounds request sizes.
- File watching covers the entry file and `sr.load` dependencies, including missing and restored files. Ordinary Python imports are not watched. Rebuild failures retain the last good mesh.
- `make build` produces the optimized binary; `make check` passes. An earlier benchmark of the unblended adapter reported roughly 1.0 s cold and 0.5–0.6 s for slot-height changes with cache reuse; this is not a benchmark of the later filleted adapter.
- The binary was tested outside the checkout. It dynamically links the build machine's Python shared library and standard library; bundling a portable Python runtime is future work.
- 2026-11-11: Viewer state synchronization after a server restart was corrected to preserve unfinished edits while updating confirmed values. The adapter viewer was opened with the selected values and blend toggles.
- Checkpoints for these changes include `ad0908b`, `743d797`, and `5f36203850d05965fe479847699cbc18c64d785c`; see the checkout inventory for recovery boundaries.
