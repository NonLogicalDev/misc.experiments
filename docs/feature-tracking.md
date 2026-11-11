# Feature and topology tracking

SolidRecipe has an initial exact identity mechanism for **one explicitly named box**, including translation and scaling. Give the primitive `with_metadata(id="stock")`. Its six faces have semantic roles such as `z_max`; an edge is identified by its two adjacent face roles, such as `x_min` and `y_min`. These identities survive box dimension changes and checked affine transforms. Roles describe the original box, so a reflection does not rename its faces by their new world position.

`shape.face("z_max")` and `shape.edge("x_min", "y_min")` return current inspection data including the structured identity. `another_shape.resolve(identity)` resolves that identity on the current shape or errors. `sr.inspect_data` reports `identity_status`: `exact_named_box` when supported, `unavailable` otherwise. Indices in inspection remain temporary.

This is deliberately narrow: **Boolean operations, fillets, chamfers, cylinders, assemblies and splits do not yet carry persistent identities.** An identity cannot be resolved through those operations. A feature name must be unique within the intended model; multiple named boxes and instance identity are not implemented. Do not infer exact identity from geometric edge points.

## Evidence in the pinned kernel

- `solidcore-record/src/brep/history.rs` defines provenance records for result faces and edges, including operand origins, splits, merges and meetings. Those are data types, not proof that every operation reports complete history.
- `solidcore-ops/src/provenance.rs` defines application-provided rules and kernel hooks for carrying attributes through split, merge and coincidence. Its `attach` and `read` functions are currently `pub(crate)`, and the public Boolean operation returns only a body. SolidRecipe cannot currently attach and retrieve those attributes through the public ops API.
- `Body::to_record()` returns a record and an `Order` connecting current record indices to kernel entities. Box identities follow those kernel entity handles through affine transforms and refuse resolution if a handle cannot be mapped.

## Next steps

1. Define explicit graph feature and instance identities, with duplicate checking and behavior for repeated modules and copies.
2. Prototype an upstream-compatible ops API that can attach and read typed provenance using record order, or expose operation history directly. Prove behavior for the pinned Boolean and blend operations before promising it as stable. Avoid modifying the vendor submodule silently.
3. Carry primitive origins through operations. Name newly created edges using the origins of the faces they join, retaining multiple origins for merges and explicit split results.
4. Expose resolution status: exact, split, merged, missing, or unverified. Refuse ambiguous selections rather than silently picking a nearby edge.
5. Exercise parameter changes, moved and split features, merges, duplicate instances, and vanished edges before using references for manufacturing operations.
