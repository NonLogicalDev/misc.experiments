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
