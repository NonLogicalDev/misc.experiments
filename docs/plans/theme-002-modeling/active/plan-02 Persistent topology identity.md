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

- Status: active; next work is not yet assigned to a worker.
- An explicitly named box (`with_metadata(id="stock")`) has semantic face and edge identities, reported by `sr.inspect_data`; `shape.face`, `shape.edge`, and `shape.resolve` query them. Identity survives checked box dimension changes and affine transforms. The tests compare identities across edits and verify current measurements.
- Boolean operations, fillets, chamfers, cylinders, multiple named parts and assemblies explicitly report identity unavailable. The adapter's point-selected fillets do not demonstrate persistent identity.
- The pinned SolidCore contains provenance hooks and history data types, but the current `solidcore-ops` attach/read hooks are private and Boolean returns only a body. This is a concrete integration boundary, not proof that full history is unavailable in every kernel path.
- Inspect `docs/feature-tracking.md` and the pinned submodule before choosing how to expose provenance. Preserve a reproducible submodule checkout; do not silently introduce an inaccessible local-only dependency commit. Avoid claiming general identity until exact propagation and failure cases are demonstrated.

## Work log

- 2026-11-11: User requested persistent face and edge identities after asking to use earlier geometry in calculations. Added in-process `shape.measure()` and `sr.inspect_data`, then implemented named-box semantic identities with explicit unavailable status outside supported operations. Validated dimensions and transforms in Rust and through embedded Python. The current source and checks are checkpointed in `5f36203850d05965fe479847699cbc18c64d785c`.
