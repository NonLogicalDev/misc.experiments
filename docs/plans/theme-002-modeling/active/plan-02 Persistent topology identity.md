# Persistent topology identity

## Purpose

Let models refer to earlier faces and edges through edits, and use those references safely in calculations and later operations. [Owners](../../OWNERS.md).

## Scope and completion criteria

- [x] Establish an exact, deliberately limited identity case for one explicitly named box, including resizing, translation and scaling; expose current face/edge data and identity resolution.
- [ ] Define stable graph feature and instance identities, including duplicate handling and repeated module instances.
- [ ] Obtain and compose trustworthy operation provenance for Boolean cuts, joins, splits and blends. Report missing, split, merged or ambiguous references explicitly; never silently select a nearby entity.
- [ ] Allow supported identities to drive later geometry operations and calculations. Verify changes to input dimensions, split/merge cases, transforms, repeated instances and vanished features.
- [ ] Validate the resulting behavior against the adapter and document which operations carry exact identity.

## Current state

- Status: active. The current owner is investigating an in-process integration; no subagents are assigned.
- Current next action: find a reproducible way to expose SolidCore provenance without an inaccessible submodule commit, then verify propagation through cuts and blends before using it in examples.
- An explicitly named box (`with_metadata(id="stock")`) has semantic face and edge identities, reported by `sr.inspect_data`; `shape.face`, `shape.edge`, and `shape.resolve` query them. Identity survives checked box dimension changes and affine transforms. The tests compare identities across edits and verify current measurements.
- Boolean operations, fillets, chamfers, cylinders, multiple named parts and assemblies explicitly report identity unavailable. The adapter's point-selected fillets do not demonstrate persistent identity.
- The pinned SolidCore contains provenance hooks and history data types, but the current `solidcore-ops` attach/read hooks are private and Boolean returns only a body. This is a concrete integration boundary, not proof that full history is unavailable in every kernel path.
- Inspect `docs/feature-tracking.md` and the pinned submodule before choosing how to expose provenance. Preserve a reproducible submodule checkout; do not silently introduce an inaccessible local-only dependency commit. Avoid claiming general identity until exact propagation and failure cases are demonstrated.

## Work log

- 2026-11-11: User requested persistent face and edge identities after asking to use earlier geometry in calculations. Added in-process `shape.measure()` and `sr.inspect_data`, then implemented named-box semantic identities with explicit unavailable status outside supported operations. Validated dimensions and transforms in Rust and through embedded Python. The current source and checks are checkpointed in `5f36203850d05965fe479847699cbc18c64d785c`.

- 2026-11-11: User rejected stopping at box-only identities and asked to keep going through Boolean operations and blends. User also asked to update examples. Investigating how to expose the pinned kernel's provenance without guessing or breaking submodule reproducibility; update this plan as evidence and implementation change.
- 2026-11-11: The pinned `solidcore-ops` exposes the provenance trait but keeps attach/read and body locks private. Considered a generated wrapper that recompiles upstream internals, but it would couple the project to private module layout. Investigating SolidCraft's existing provenance-capable kernel boundary in a temporary checkout before deciding; preserve the pinned submodule and avoid guessed identity.
- 2026-11-11: SolidCraft's public wrapper exposes tagged operands and exact history, but it uses a separate vendored SolidCore and record types; the temporary sparse checkout is 538 MB. Determine whether one shared kernel can be used before choosing it. Added an example of the existing named-box reference and its explicit limits while provenance work continues.
- 2026-11-11: Ran the new identity example through the embedded runtime; its old edge identity resolved to the resized box's 14 mm edge. `make check` passed (7 Rust and 13 Python tests, formatting and lint). Boolean and blend history remains unfinished; the example does not claim otherwise.
- 2026-11-11: User clarified the finish criterion: continue until identities work through the requested operations end to end. The earlier example/checkpoint is not completion. Investigating a single-kernel integration using SolidCraft's provenance wrapper and its pinned SolidCore tree; require exact order mapping, explicit split/merge/deletion results, identity-based downstream operations, and end-to-end tests before closing this plan.
- 2026-11-11: User clarified that composition is a graph, not a timeline. Define feature and instance identity over dependency-graph nodes and explicit graph paths; propagate provenance along graph edges and handle branching, reuse, and repeated instances without timeline-order semantics.
- 2026-11-11: A temporary Rust probe using SolidCraft's provenance wrapper built with Rust 1.97 and executed a box cut and fillet. The cut reported a face split into two results and source origins from both operands; the fillet reported surviving face origins and a generated face. The probe is outside the project and does not establish SolidRecipe integration or identify generated blend faces. Next: establish a reproducible single-kernel dependency and integrate operation history into graph evaluation.
- 2026-11-11: Added `vendor/solidcraft` as a pinned submodule at `9e805b7b` for integration investigation. Its `solidcraft-kernel` exposes validated Boolean and blend history in canonical record order, avoiding a project-owned wrapper around private kernel internals. Its embedded SolidCore tree differs from the existing pinned submodule, so the integration must use a single copy consistently and validate existing operations before accepting the dependency.
- 2026-11-11: SolidRecipe compiles against the single SolidCore tree embedded in pinned SolidCraft after adapting the blend options API. Running the full existing suite before proceeding. SolidCraft's public body constructor does not accept a raw record directly, so the integration must preserve and verify canonical ordering through its supported boundary rather than assume imported entity order.
- 2026-11-11: Full `make check` passed on the single-kernel dependency change: 7 Rust tests, 13 Python tests, formatting, lint, and viewer build. A record-import probe showed that serialization changes even for a box, despite identical entity counts and identity native order; graph-to-kernel correspondence must be checked instead of comparing serialized bytes or assuming input order.
