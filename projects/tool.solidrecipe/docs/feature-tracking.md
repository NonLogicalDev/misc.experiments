# Feature and topology tracking

SolidRecipe can track semantic faces and edges of explicitly named boxes through selected graph operations. The implementation is experimental: the kernel's provenance callbacks are not yet proven complete for every geometry and operation. Do not use an unverified reference as evidence of manufacturing correctness.

Give a box `with_metadata(id="stock")`. Its faces have roles such as `z_max`; an edge is identified by the two adjacent roles, such as `x_min` and `y_min`. Roles describe the original box, so reflection does not rename them by world position. Named-box references have been exercised across dimension changes, transforms, selected Boolean operations, and blends.

`shape.face("z_max")` and `shape.edge("x_min", "y_min")` return current inspection data with an `identity`. Use `another_shape.resolve(identity)` to find a unique, unmerged descendant and read its current measurements. `shape.fillet(edge_refs=[identity], radius=...)` and `shape.chamfer(edge_refs=[identity], distance=...)` select edges on the evaluated operand. The existing `edge_points` option remains a separate geometric selector. Inspection indices apply only to the current result.

Use `shape.instance("left")` to namespace identities when placing a reusable shape more than once; nested instances add path components. Names must be unique within a scope. A shared authored graph node may be reused, but distinct declarations with the same name in one scope are rejected. Occurrence tokens in serialized Python graphs validate sharing within that graph; they are not persistent identity components.

Multiple descendants cause resolution to report split or ambiguous. Multiple origins, including a merge with an unnamed entity, are reported as merged and cannot drive a reference-selected blend. An identity known to the graph with no reported descendants is reported as `no surviving tracked descendant; deleted or untracked`; an unknown identity is reported as unknown or unavailable. The implementation does not yet prove whether an absent descendant was deleted or its provenance was lost. Generated faces and edges do not yet have stable identities, and named cylinders do not create semantic identities. `identity_status` describes the reporting path, not a proof of complete history.

## Kernel integration and remaining work

SolidRecipe attaches operation-local tags to faces and edges on the actual SolidCore bodies. Kernel callbacks carry those tags through operations, and the evaluator maps them to the input reports. Geometry, record order, and report travel together; cached copies use the kernel copy map. This avoids mapping between independently imported bodies. The pinned SolidCraft submodule needs the versioned API patch applied by `make prepare-solidcore`; see the repository README for setup.

The callback-based results need broader evidence for cuts, unions, intersections, fillets, chamfers, shared branches, repeated module instances, parameter edits, and negative cases. Untagged results cannot safely be called generated or associated by proximity, and missing tags do not prove deletion. Complete those semantics and tests before treating general topology identity as finished.
