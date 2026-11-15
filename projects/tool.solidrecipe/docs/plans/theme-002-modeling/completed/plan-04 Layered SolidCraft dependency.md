# Layered SolidCraft dependency

Status: completed. [Owners](../../OWNERS.md).

Replace SolidRecipe’s bespoke SolidCraft patch preparation with a reproducible layerctl workflow while preserving the current pinned source, five ordered patches, local vendor checkout, and build behavior. The existing checkout and build artifacts must remain recoverable throughout the change.

A disposable layerctl projection reproduced the current vendor diff byte for byte using the pinned SolidCraft commit and all five patches. Layerctl currently discovers definitions at a Git repository root, while SolidRecipe is nested in misc.experiments; choose a durable definition location and validate a clean setup before changing the build.

Decision: retain the pinned SolidCraft submodule as the clone source and the five versioned patches. A generated local definition repository and projection under an ignored project directory allow layerctl to operate inside the larger misc.experiments checkout. Cargo will use the projection, leaving the existing vendor tree untouched. Refuse to replace an incomplete, stale, or modified projection, and reject unexpected source-submodule changes rather than silently ignoring them.

The disposable workflow reproduced the current vendor diff byte for byte, was idempotent, and rejected a modified projection. Next: integrate it into preparation and Cargo, then validate fresh setup and a focused build.

Validation: the layered diff matched the prepared submodule byte for byte; first and repeated preparation succeeded; modified workspaces, stale inputs, and unexpected source files were rejected. `cargo check --workspace --offline` passed after refreshing the CLI build script timestamp; `cargo test -p solidrecipe-core --offline` passed 40 tests. The original submodule diff was preserved. The generated workspace is local and can be rebuilt as documented in the project README.
