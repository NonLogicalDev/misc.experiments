# Rust preview and graph caching

SolidRecipe's Rust CLI owns local HTTP, source watching, presets and rebuild orchestration. It embeds Python through PyO3 for in-process model evaluation, and calls the Rust geometry core directly. It neither launches Python per rebuild nor writes graphs to temporary files. The viewer assets are extracted privately because the local HTTP server serves them as files.

Unchanged expression subtrees reuse in-memory B-reps through `BuildCache`; each key includes the full graph subtree. SolidCore Boolean operations consume their operands, so cached bodies are copied when reused. The cache is bounded by the graph of the latest successful evaluation. A failed evaluation preserves the last successful model and the prior cache.

Python `sr.load` records exact sources used for each module. The watcher compares those bytes, including missing modules, so edits and recovery trigger reevaluation. Standard Python imports are outside that tracking. A new build invalidates only graph subtrees whose inputs or values differ; this is an execution cache, not persistent feature identity.

The same process executes user model code and the local server. This removes subprocess overhead and isolation: a nonterminating or native-crashing model may block or terminate the application. Python's dynamically linked runtime is a deployment dependency. See `feature-tracking.md` for the separate topology naming design.
