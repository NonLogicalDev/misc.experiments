# Modeling modules and adapter

## Purpose and scope

Exercise the new code-first engine with the NH-L12S cooler adapter while providing reusable Python module and shape APIs. Preserve the original manufacturing design in the separate `homelab-cooler-adapters` project. This is a SolidRecipe prototype, not authorization to change or submit manufacturing files. [Owners](../../OWNERS.md).

## Result

- Python models use `import solidrecipe as sr`. `sr.module` creates a file-local namespace; `@sr.exportf` exports a function by its Python name, with an optional alias; `sr.export(shape)` provides the default shape; `sr.load` imports a file's exports. `typing.Annotated` and `sr.Param` describe function parameters for the viewer.
- The Rust core evaluates B-reps and caches unchanged expression subtrees. Box and cylinder primitives, Boolean operations, translation, scaling, and kernel fillet/chamfer operations are available. Blend selectors use model-space points; they are not persistent topology references and ambiguous picks fail.
- `sr.inspect` emits JSONL; `sr.inspect_data` returns B-rep details in-process; `shape.measure()` reports bounds and volume for later calculations. `with_metadata` retains author metadata on graph nodes.
- `examples/cooler_adapter.py` exports `mounts.adapter`, with controls for side, slot height, 2 mm entry fillets and 1 mm full-length underside chamfer. It uses the new module API. The source design is `homelab-cooler-adapters/manufacturing/slot-height-variants-label-08`.
- The 0.5 mm ledge fillet, outer rounding and labels are absent. SolidCore returned `Status(1001)` in the isolated ledge-fillet probe. Physical fit, structural behavior, and equivalence to the submitted file are unverified.

## Work log and evidence

- 2026-11-11: Replaced per-rebuild Python processes with an embedded interpreter; Rust owns the preview coordinator and graph cache. Added file-scoped modules and annotated parameters. Local checkpoint `743d797` records this stage.
- 2026-11-11: Added transforms, in-process measurements and geometric-point blends. Both halves with all three slot heights built successfully with the entry fillets and underside chamfer. Both halves also built for every combination of the two blend toggles at 4.6 mm. `make check` passed after implementation. Named-box identity began in the same checkpoint `5f36203850d05965fe479847699cbc18c64d785c`; its limited scope and remaining work are in the topology plan.
- 2026-11-11: Opened the optimized viewer at `http://127.0.0.1:8765/`; left half, 4.5 mm slot, and both blend controls were selected at verification. The server is an ephemeral local process and must not be assumed to survive.

## Remaining limitations

- Slot-entry fillets are applied before the lower setback because applying them afterward produced a kernel size refusal. The full-length bottom chamfer succeeds; the 0.5 mm ledge fillet requires further investigation.
- Edge-point selection tests uniqueness among kernel-resolved edge queries. Stable identification through Boolean and blend operations is not implemented. Do not substitute a geometric guess for topology provenance.
