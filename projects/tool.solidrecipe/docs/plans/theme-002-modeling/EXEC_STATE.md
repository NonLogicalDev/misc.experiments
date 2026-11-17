# Modeling and topology

## Goal

Build file-first, code-driven B-rep modeling and reusable modules, with reliable geometry references and an inspectable adapter example.

## Current state

- [Layered SolidCraft dependency](completed/plan-04%20Layered%20SolidCraft%20dependency.md): layerctl migration completed and validated; the original vendor checkout is preserved.
- [SolidCraft layer definitions](active/plan-05%20SolidCraft%20layer%20definitions.md): checked-in layerctl definitions own every SolidCraft patch and fetch its pinned source directly; the redundant upstream checkout was removed. Root packaging has been reorganized. Offline Rust workspace check passed; full runtime tests remain outstanding.

- Status: active. Same-body provenance, named graph instances and reference-selected blends have existing tests. A richer operation-local history DAG now passes focused structural tests but is not connected to evaluation. Definitive deletion and generated-entity attribution in the production evaluator remain unproved.
- Initial planar sketch extrusion now supports line, arc, cubic and interpolated curves, intersection-derived closed regions, and offsets through the SolidCraft sketch engine. Point-based region selection is sampled and can retarget after edits; it is not persistent identity. Difficult offsets can fail. Constraints, face attachment and path sweeps remain future work. Thirteen profile integration tests and 33 core tests passed; a temporary preview served an extruded sketch without error. Task-created incremental build caches and the temporary preview were removed after testing.
- [Modeling and adapter implementation](completed/plan-01%20Modeling%20modules%20and%20adapter.md) records the accepted API, checks, and limitations.
- [Persistent topology identity](active/plan-02%20Persistent%20topology%20identity.md) records the unfinished general identity work and next action.
- [General topology queries and face-attached profiles](active/plan-03%20General%20topology%20queries%20and%20face-attached%20profiles.md) records the current research and design work.
- [Construction query study](../_owner/docs/construction-query-study.md) records the proposed general operators, experiments, counterexamples and limits.
- The adapter source is `examples/cooler_adapter.py`. It is a comparison prototype, not a verified manufacturing file.
- See the [checkout inventory](../_owner/state/worktrees.md) for local recovery limits.
