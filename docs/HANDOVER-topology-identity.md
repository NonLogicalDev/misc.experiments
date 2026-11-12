# Handover: persistent topology identity

Updated: 2026-11-11. This work is in progress. Do not treat the current working tree as a finished implementation.

## Goal and constraints

Implement persistent face and edge references through Boolean operations and blends, usable in later geometry and calculations. SolidRecipe composition is a dependency graph, not a timeline: support branches, reused features, and repeated module instances with unambiguous instance identity. Explicitly report deleted, split, merged, and ambiguous references; do not silently select a geometrically nearby entity. Verify the behavior end to end, update examples, and keep the Tasker Stream plan current as working memory. The user wants Rust to own geometry and execution without shelling out, dependencies pinned as vendor submodules, and frequent local Git checkpoints.

Read the project `AGENTS.md`, `docs/plans/MEMORY.md`, `docs/plans/OWNERS.md`, and [the active topology plan](plans/theme-002-modeling/active/plan-02%20Persistent%20topology%20identity.md) before changing the project. Confirm current ownership and working-tree state. The user's finish criterion is a working end-to-end result, not a partial demonstration.

## Checkout and current state

- Project: `/Users/nonlogical/Projects/local/active/tool.solidrecipe`.
- Latest checkpoint at handover: `fc9e8ca` (pin single kernel with history support). It adds `vendor/solidcraft` at `9e805b7b`, points SolidRecipe's SolidCore dependencies at its embedded SolidCore tree, and adapts the blend options API. The prior `vendor/solidcore` submodule remains present; do not silently change or remove it.
- At the latest status check, uncommitted work included `Cargo.lock`, `docs/plans/OWNERS.md`, the active topology plan, `src/solidrecipe-core/Cargo.toml`, `src/solidrecipe-core/python/solidrecipe.py`, `src/solidrecipe-core/src/lib.rs`, `tests/test_inspect.py`, the new `src/solidrecipe-core/src/provenance.rs`, and this handover. Recheck Git status and ownership before resuming; preserve the draft and any unrelated work.
- `examples/topology_identity.py` demonstrates the earlier named-box identity support; its stated Boolean/blend limits may be stale as the draft develops. `examples/cooler_adapter.py` is a comparison prototype, not a verified manufacturing model.

## What the draft does

- `provenance.rs` converts existing SolidCore bodies through SolidCraft's history-aware boundary. It checks numbered vertices, edges, and face-loop incidence on both sides of the conversion and refuses mismatches. It obtains Boolean and blend history via `solidcraft-kernel`.
- `inspect_tracked` composes reported origins through Boolean and blend nodes. `apply_history` retains multiple input identities on merged entities and repeats an identity for split descendants. Transform handling carries identity fields by kernel handles.
- The draft now uses one tracked evaluation for building and inspection. `BuildCache` stores a body and its report together; copies map entity order through the kernel's copy map and regenerate measurements. Cache keys omit graph-node occurrence tokens, and names are validated before cache reuse. Validate this path through the real CLI and viewer as well as the focused cache tests.
- Python `Shape.instance(name)` introduces an explicit namespace; Rust adds the instance path to identities and rejects duplicate names in a scope unless the same authored node is reused. Python assigns process-local occurrence tokens to distinguish shared nodes from independent nodes during graph validation; these tokens are not persistent topology identities.
- Python lookup checks singular and multiple identities, ignores nulls, and reports merged, split or ambiguous, and missing or unavailable results. Missing and unavailable are not yet distinguishable from deletion. Fillets and chamfers still take point selectors, not persistent references.
- **Exact correspondence remains unproven.** `same_numbering` compares coordinates, edge endpoints, and face incidence after import/export, but it cannot establish that coincident vertices or distinct curved edges with the same endpoints and incidence retain their identity. It also ignores loop orientation and ordering. Review found no public original-record-to-SMLib mapping in the current import boundary. A robust solution needs kernel support for that mapping or a single authoritative representation that avoids this bridge; do not claim general exact identity from the current guard.

## Verified evidence and latest interruption

- At checkpoint `fc9e8ca`, `UV_CACHE_DIR=/tmp/solidrecipe-uv-cache make check` passed: 7 Rust tests, 13 Python tests, formatting/lint, and the viewer build. This was before the uncommitted history implementation.
- A temporary SolidCraft probe reported both source operands and a split face for a cut, and preserved face origins for a fillet. Temporary probe files were removed.
- On the draft as checked, `UV_CACHE_DIR=/tmp/solidrecipe-uv-cache make check` passed formatting, viewer build, clippy, lint, the workspace build, and all 12 Rust tests, including the Boolean, blend, instance and cached-body tests. The command failed in the Python stage: 15 tests ran with 3 errors and 1 failure in viewer-server tests. Later edits require a fresh check.
- The viewer tests did not receive a server URL. The actual CLI command exited with `Operation not permitted (os error 1)`; an independent Python bind to `127.0.0.1:0` also failed with `PermissionError`, confirming the sandbox blocks local server binding. The test cleanup also encountered sandbox-denied `killpg`; passing outside the sandbox remains unverified. Retry the affected tests in an environment that permits local sockets and process cleanup.
- Earlier compiler artifacts disappeared during a build, and an earlier separate kernel build exhausted disk space. Their causes were not established. Check build activity and available space before cleaning or restarting work; do not kill unrelated processes or remove shared build state without understanding ownership.

## Next work

1. Resolve the unproven kernel correspondence before relying on Boolean or blend history as exact. Verify behavior for coincident vertices, curved edges, loop order and orientation, and reordered entities.
2. Complete and review graph feature and instance semantics for repeated modules and shared branches. Define and test explicit split, merge, deletion, generation, unsupported and ambiguity outcomes; don't infer deletion from missing provenance.
3. Make supported references drive downstream fillets/chamfers and calculations against the same evaluated body and entity order, without converting references into unchecked point guesses. Cover Boolean cuts, unions, intersections, both blend types, transforms, parameter edits, instances, and negative cases.
4. Update the adapter and examples to demonstrate the finished API and its limits. Verify real CLI and viewer behavior, rerun full repository checks in an environment that permits localhost, review the complete diff, update the live plan, and checkpoint locally.
