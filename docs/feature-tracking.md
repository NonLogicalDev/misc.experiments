# Feature and topology tracking

`Shape.with_metadata(...)` preserves author-supplied metadata on each construction graph node. `sr.inspect(...)` reports that graph alongside actual B-rep geometry. Neither assigns persistent face or edge identities; inspection indices refer only to the evaluated record and must not be reused after rebuilding.

## Evidence in the pinned kernel

- `solidcore-record/src/brep/history.rs` defines provenance records for result faces and edges, including operand origins, splits, merges and meetings. Those are data types, not proof that every operation reports complete history.
- `solidcore-ops/src/provenance.rs` defines application-provided rules and kernel hooks for carrying attributes through split, merge and coincidence. Its `attach` and `read` functions are currently `pub(crate)`, and the public Boolean operation returns only a body. SolidRecipe cannot currently attach and retrieve those attributes through the public ops API.
- `Body::to_record()` returns a record and an `Order` connecting the current record indices to kernel entities. These indices are useful for inspection, but are not promised to persist across graph edits.

## Proposed route

1. Give graph nodes explicit user-stable identities, separate from display names and the JSON serialization order. Define uniqueness and behavior for copies and repeated instances.
2. Prototype an upstream-compatible ops API that can attach and read typed provenance using record order, or expose operation history directly. Prove the behavior for our pinned Boolean and blend operations before promising it as stable. Avoid modifying the vendor submodule silently.
3. Assign primitive face roles and carry their origins through operations. Name newly created edges using the origins of the faces they join, retaining multiple origins for merges and explicit split results.
4. Expose resolution status: exact, split, merged, missing, or unverified. Refuse ambiguous selections rather than silently picking a nearby edge. Geometric queries can help users select candidates, but cannot prove identity.
5. Exercise parameter changes, moved and split features, merges, duplicate instances, and vanished edges before using these references for manufacturing operations.

This is a design direction, not an implemented guarantee. Fillets, chamfers, viewer edge selection, and provenance propagation are not yet implemented in SolidRecipe.
