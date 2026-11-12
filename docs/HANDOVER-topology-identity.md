# Handover: persistent topology identity

Updated: 2026-11-11. This work is in progress. Do not treat the current working tree as a finished implementation.

## Goal and constraints

Implement persistent face and edge references through Boolean operations and blends, usable in later geometry and calculations. SolidRecipe composition is a dependency graph, not a timeline: support branches, reused features, and repeated module instances with unambiguous instance identity. Explicitly report deleted, split, merged, and ambiguous references; do not silently select a geometrically nearby entity. Verify the behavior end to end, update examples, and keep the Tasker Stream plan current as working memory. The user wants Rust to own geometry and execution without shelling out, dependencies pinned as vendor submodules, and frequent local Git checkpoints.

Read the project `AGENTS.md`, `docs/plans/MEMORY.md`, `docs/plans/OWNERS.md`, and [the active topology plan](plans/theme-002-modeling/active/plan-02%20Persistent%20topology%20identity.md) before changing the project. Confirm current ownership and working-tree state. The user's finish criterion is a working end-to-end result, not a partial demonstration.

## Checkout and current state

- Project: `/Users/nonlogical/Projects/local/active/tool.solidrecipe`.
- Checkpoint `f7e7de9` contains the same-body provenance draft, versioned patch and preparation script. The earlier checkpoint `fc9e8ca` pins `vendor/solidcraft` at `9e805b7b` and points SolidCore dependencies at its embedded tree. The prior `vendor/solidcore` submodule remains present; do not silently change or remove it.
- The prepared `vendor/solidcraft` checkout intentionally contains the tracked patch's modification. Recheck Git status and ownership before resuming; preserve any unrelated work.
- `examples/topology_identity.py` demonstrates a reference-selected fillet after resizing and cutting a named box. `examples/cooler_adapter.py` is a comparison prototype, not a verified manufacturing model. Its generated setback edge still uses a point selector because it has no persistent identity.

## What the draft does

- `provenance.rs` attaches operation-local tags to faces and edges of the same SolidCore bodies used for geometry, and reads kernel callbacks after each Boolean or blend. The versioned patch under `patches/vendor/` exposes the required ordered read/write API; `make prepare-solidcore` applies it to the pinned submodule.
- `inspect_tracked` composes reported origins through Boolean and blend nodes. `apply_history` retains multiple input identities on merged entities and repeats an identity for split descendants. Transform handling carries identity fields by kernel handles.
- The draft now uses one tracked evaluation for building and inspection. `BuildCache` stores a body and its report together; copies map entity order through the kernel's copy map and regenerate measurements. Cache keys omit graph-node occurrence tokens, and names are validated before cache reuse. Validate this path through the real CLI and viewer as well as the focused cache tests.
- Python `Shape.instance(name)` introduces an explicit namespace; Rust adds the instance path to identities and rejects duplicate names in a scope unless the same authored node is reused. Python assigns process-local occurrence tokens to distinguish shared nodes from independent nodes during graph validation; these tokens are not persistent topology identities.
- Python lookup checks singular and multiple identities, ignores nulls, and reports merged, split or ambiguous, known identities without a surviving tracked descendant, and unknown or unavailable identities. It does not infer deletion from absent provenance. Fillets and chamfers accept `edge_refs` as well as their original point selectors; the evaluator resolves references on the operand body and refuses missing, split, merged, ambiguous, or duplicate selections.
- The former record-import correspondence guard was removed with the switch to operation-local tags on the authoritative bodies. **Callback completeness remains unproven:** untagged results cannot safely be classified as generated, and a missing tag does not prove deletion. Generated faces and edges do not yet receive stable identities. Do not claim general exact identity from the current tests.
- The stitch notification patch routes the tested face-edit notification through the real attribute store. A scoped audit rejects Boolean and blend results when an application handler or placement reports an error at `run_application`, even if the kernel ignores it; it does not detect omitted notifications or other errors. The audit is thread-local and relies on synchronous callback delivery. A real Boolean regression verifies rejection and cache recovery.
- An isolated blend-face lineage probe traced a selected edge to a stitched face for box fillet/chamfer and a cut-shape fillet, but did not establish complete lineage. The normal stitch path previously sent face PreEdit through an empty attribute store and may swallow ordinary notification errors. A versioned patch repairs that specific notification path; operation-scoped callback-error tracking is in progress. The temporary probe was removed after its findings were recorded. Do not assign generated identities without auditing the remaining kernel paths, ambiguity and rollback behavior.

## Verified evidence and latest interruption

- At checkpoint `fc9e8ca`, `UV_CACHE_DIR=/tmp/solidrecipe-uv-cache make check` passed: 7 Rust tests, 13 Python tests, formatting/lint, and the viewer build. This was before the uncommitted history implementation.
- A temporary SolidCraft probe reported both source operands and a split face for a cut, and preserved face origins for a fillet. Temporary probe files were removed.
- The latest `UV_CACHE_DIR=/tmp/solidrecipe-uv-cache make check` passed with localhost access: formatting, lint, build, 22 Rust core tests, 6 kernel integration tests and 20 Python tests. Subsequent changes to the audit patch were documentation comments only. Both updated examples also produced preview meshes through the embedded server. Repeat affected checks after further edits.
- The sandbox blocks localhost socket binding and process-group cleanup; run viewer tests where those are permitted. At `f7e7de9`, an isolated checkout reconstructed both pinned submodules from local Git objects, installed viewer packages from the local offline store, and passed the full offline `make check` with localhost access (20 Rust and 17 Python tests). Remote dependency availability remains unverified.
- Earlier compiler artifacts disappeared during a build, and an earlier separate kernel build exhausted disk space. Their causes were not established. Check build activity and available space before cleaning or restarting work; do not kill unrelated processes or remove shared build state without understanding ownership.

## Next work

1. Establish and enforce complete operation-level lineage in the kernel, including stitch notification delivery and error handling, coincident and curved geometry, ambiguity and rollback; classify unsupported cases without choosing nearby topology.
2. Complete and test explicit deletion and generation semantics, graph instances and shared branches. Cover Boolean cuts, unions and intersections, both blend types, transforms, parameter edits, and negative cases through the real entry points.
3. Give generated entities stable references where supported, then revisit the adapter's generated setback edge without changing its geometry.
4. After changes, repeat affected checks through the real entry points, review the complete diff, update the live plan, and checkpoint locally.
