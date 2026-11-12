# Topology queries and face-attached profiles

**Working design, 2026-11-11.** This document records alternatives for discussion. Its API examples are illustrative; they are not implemented contracts. The active [planning record](../../theme-002-modeling/active/plan-03%20General%20topology%20queries%20and%20face-attached%20profiles.md) owns the work.

## The modeling problems

The user wants to describe geometry on arbitrary shapes without memorizing box-specific face names or extracting an `identity` field from an inspection dictionary. In one example, a larger and smaller solid are combined with a Boolean, then a subset of the intersection edges is filleted. The user also wants to subdivide edges, and to extrude a 2D profile attached to a face, with constraints to geometry projected into that profile.

Those requests involve several related but different questions:

- **Selection:** Which current faces, edges or vertices satisfy the author's criteria?
- **Continuity:** Which current entity descends from a particular earlier one?
- **Construction:** Which entities were created or modified by a particular operation, and from which inputs?
- **Geometry:** Where is a sketch frame, what is projected into it, and what are the solved profile's curves?
- **Recovery:** When the system cannot establish the intended correspondence, what evidence lets a human or model choose a repair?

One type of identifier cannot answer all of these questions. In particular, a unique geometric query today does not prove that it will continue to select the same entity after an edit.

## Query model: agreed direction

The user prefers a small composable query language over a growing collection of narrowly tailored fluent methods. Select entities, express general relationships and geometric predicates, and combine them. Fluent conveniences may be added where useful, but they should compose the same core model rather than define a separate concept for every modeling task. The exact syntax and primitive vocabulary remain open.

Represent queries as composable descriptions of sets, bound to a graph result and instance context. On each rebuild, resolve a query against that result's current body, record and kernel order—the same ones the consuming operation uses. A query is not a saved array of entity indices. Inspection snapshots are separately bound to one evaluated revision.

```text
For each edge e in cut, select e when:
  there exist distinct faces f and g in cut such that
    e is incident to f and g,
    f has stock as an origin, and g has tool as an origin;
  and the whole edge is on the positive side of datum_plane.
Fillet the selected edges.
```

This is a specification, not proposed Python syntax. The earlier sketch used two independent adjacency checks, which could both be satisfied by one merged face with origins from both operands. The corrected version explicitly binds two distinct faces. The [query algebra and evidence](topology-query-algebra.md) explain the required general operations and the limits of the proof.

This sketch expresses a set, not an assumed number of edges. An operation may require a nonempty set; the author may additionally assert an expected count or require one result. A count can detect some changes, but two different sets can have the same count. Query evaluation after a parameter edit may intentionally select a different set that satisfies the same criteria; it is not equivalent to following a particular persistent entity.

Here `on_side_of` is a proposed general predicate, not an implemented API. The positive side is the side pointed to by the plane's normal; `match="entire"` means the whole entity must lie on that side. The exact naming, defaults, treatment of entities touching the plane, and tolerance remain to be designed. Prefer language that makes the side and behavior clear to model authors over mathematical jargon such as “half-space.”

An interface query needs an exact contract. One possible definition is edges incident to output faces whose verified origins belong to opposite operands. That is not the same as “edges newly created by the Boolean”: a coincident or pre-existing contact edge can belong to an interface. Other useful concepts include created-by, modified-by, adjacent-to, owned-by, and descendants-of. Do not call any of them complete until its underlying lineage can support that claim. The user should be able to combine geometric and construction predicates without depending on boxes.

An eventual contract must say whether operand membership means the immediate inputs to one identified Boolean or transitive origins elsewhere in the graph. Reused branches and instances need distinct occurrence scopes even when geometry is identical. It must also specify crossing versus tangent contact, coincident faces, inherited edges, same-source adjacency, merged faces, and unknown contributors. Set algebra must preserve the body and revision domain; mixing snapshot handles from different bodies or revisions requires an explicit mapping.

In particular, today's single observed source tag is not proof that no other source was missed: the audit records only certain failures in callbacks that reached it. Until the relevant operation path has a completeness certificate, an interface search based on those tags can present diagnostic candidates, but cannot certify an exhaustive selection for a modeling operation. Unknown must be assigned based on coverage, not only when a tag happens to be absent.

An edge shared by two faces is not necessarily unique. A plane and a cylindrical slot surface can meet in two edges with the same supporting-face pair; a feature-relative half-space or another authored discriminator may distinguish them. Symmetry can leave no unique choice. `between_faces` is therefore naturally a set query; `.one()` should refuse multiple matches. A supporting-face naming scheme that prevents merging faces with different feature owners is a substantial alternative kernel/model policy, not a guarantee of the existing B-rep. [Bidarra, Nyirenda and Bronsvoort](https://graphics.tudelft.nl/~rafa/myPapers/jrnl-bidarra.CAD05.pdf), [Capoyleas, Chen and Hoffmann](https://www.cs.purdue.edu/cgvlab/www/resources/papers/Capoyleas-Computer_aided_design-1996-Generic_naming_in_generative.pdf).

Candidate query operations to evaluate:

- **Domain and type:** faces, edges or vertices of a particular body/instance; planar faces, circular edges, lines or other supported geometry.
- **Relationships:** adjacency, boundary loops, source feature, operation contribution, intersection/interface, and descendants of a reference.
- **Geometry and location:** parallel/perpendicular, facing, contained in a region, intersects a plane, entirely on one side, distance or size ranges, and extrema relative to a coordinate frame.
- **Set algebra:** intersection, union and difference of queries over a common scope; explicit conversion between faces and their boundary edges.
- **Cardinality and evidence:** all matches, one unique match, explicit count assertions, and inspectable reasons for unsupported or incomplete results.

The context of a relationship matters. An edge's convexity is defined relative to its enclosing body and adjacent faces; an isolated edge or open/nonmanifold boundary may not have the same answer. Query scope must retain the body and instance, not just the shape's geometry. [build123d topology selection](https://build123d.readthedocs.io/en/stable/topology_selection.html).

Every predicate needs a documented domain, units, tolerance, coordinate frame and meaning at a boundary. For example, a line can be parallel to a direction over its whole length; a curved edge has changing tangents. An edge crossing a plane is not entirely on either side, even if its midpoint is. A curved face has no single global normal. A seam can use the same face twice and must not be mistaken for two distinct incident faces. Do not implement a convenient name by silently sampling or choosing the first indexed match.

Extrema need a tie policy and frame: if two faces are equally far along an axis within the documented tolerance, return both and let an explicit uniqueness requirement fail. Existing closest-point calculations can be local and face areas can be estimated; a local sample or approximate measurement is not automatically a certified whole-entity predicate. An analytic carrier may also be paired with a different bounded NURBS parameterization, so edge split locations must use the actual trimmed representation.

When evidence is incomplete, a filter may have a **match**, **no match**, or **unknown** outcome. An unknown source lineage cannot be silently discarded from a provenance-based set. A known-false geometric condition can still exclude an entity. An operation must not claim a complete selected set if remaining unknowns could change it. Purely geometric queries can still work on untracked geometry if their own predicates are supported; they must not claim stable provenance as a result.

## References, indexes and recovery

- A **persistent reference** aims to identify a feature/instance and the proven lineage of an entity. One-to-many and many-to-one changes remain visible. A reference can become missing, split, merged or untracked; do not silently select a plausible replacement. Current experimental tags are useful observed origins, not a certificate of complete ancestry across every operation.
- A **snapshot handle** identifies an entity within one evaluated body/revision and supports inspection, UI highlighting and diagnostics. It must not silently remain valid after that body is rebuilt.
- A **fingerprint** is evidence for a candidate repair: for example, normalized geometry, neighborhood, prior origin and position. It is not a guaranteed stable ID. Geometry and adjacency can change, and symmetric entities can be indistinguishable even without a hash collision.
- A **repair** presents the previous intent, revision, candidate entities and reasons. A human or model can explicitly choose a replacement; record that choice and re-evaluate the dependency. A visual or geometric suggestion is not the same as an automatically proven match.

The same machine-readable diagnostic should support a viewer and an agent: include the graph/body revision and instance scope, original reference or query, candidate snapshot handles, source/geometry evidence, unknowns and completeness, coordinate frame and tolerances. A repair must check that the revision is still current before writing a new reference or query. Do not silently promote a transient snapshot handle into persistent identity.

An inspector can also show current query matches and help a person or model formulate a reusable predicate. The 2020 interactive-programming paper synthesizes predicates from selections; its evaluation distinguishes logical equivalence from agreement on sampled parameter values. A query that matches examples is useful evidence, not a proof that it encodes the intended relationship for every edit. [Mathur, Pirron and Zufferey](https://onlinelibrary.wiley.com/doi/10.1111/cgf.14046).

Open design issue: stable author-facing feature identities must survive parameter reevaluation and repeated instances without requiring a handwritten ID for every local object. Possible approaches include explicit authored names, persistent file-backed IDs, or generated IDs with a defined lifecycle. Source line numbers, transient object addresses and runtime occurrence tokens alone cannot establish continuity across edits. Compare their ergonomics, persistence and diff behavior before choosing.

- **IDs in authored source** travel with ordinary files and are reviewable, but making every temporary feature carry a manual string would be noisy. A dynamic local query should not need a durable ID unless its meaning requires one.
- **A versioned sidecar** could hold IDs, labels or explicit repairs without cluttering model code. It must travel with the source, have a clear namespace and conflict policy, and fail visibly when absent or inconsistent; otherwise copying a model can silently reassign identities.
- **Code-derived hints** such as file/line or AST position are convenient for navigation, but refactoring, repeated calls and loops can invalidate or alias them. Per-evaluation occurrence tokens establish sharing within one graph, not durable identity.

Separate display labels from stable IDs. The exact storage policy is open; the invariant is that a rebuilt graph cannot silently substitute a different authored feature merely because its location or geometry happens to match.

## Edge subdivision

Subdivision is a modeling operation on a particular evaluated body, not merely slicing a list of query results. Its output must map actual parent and child handles on the resulting body. The parent reference may resolve to multiple descendants; individually named children need a separate, proven split lineage and an unambiguous ordering or authored side definition.

Specify the split location: native curve parameter, normalized parameter, distance from an explicitly oriented endpoint, fraction of arc length, or an intersection with a datum. Half the parameter interval is not generally half the physical length. Curves without an unambiguous endpoint/orientation, near-endpoint splits, repeated locations, unsupported length inversion and partial kernel failures need explicit outcomes. Rebuilding with a changed parameter must recompute the split.

Successful subdivision does not prove the kernel can fillet only one resulting segment. The current SolidCore blend API can reject an edge that continues into a tangent neighbor. Test split → select child → fillet on real solids before promising partial-edge blends.

A first-class partial fillet is a separate product and kernel capability from splitting topology and filleting a child. For example, Onshape exposes partial-fillet boundaries based on endpoint percentages, distances and reference planes. Its edge-splitting API separately defines arc-length and native-parameter modes. Compare the two resulting geometries and failure behaviors; do not imply that one is automatically implemented by the other. [Onshape fillet](https://cad.onshape.com/help/Content/PartStudio/fillet.htm), [Onshape operation API](https://cad.onshape.com/FsDoc/library.html).

SolidCore has an opt-in tangent-continuation termination fix with an upstream test that rounds an arc ending at tangent straight edges. SolidRecipe does not currently enable that fix. This is a reason to test, not evidence that an artificial split of a straight or circular edge yields a controllable partial fillet. A whole-edge variable-radius law is also not automatically a bounded partial fillet.

## Face-attached profiles

Treat a sketch/profile and its support as graph values with explicit dependencies:

```text
host body → face selection/reference → attachment frame
source geometry → projection into frame → sketch constraints
sketch geometry + constraints → solved profile → extrusion → union/cut
```

The first implementation can restrict a support to a verified planar face. A face normal specifies only one axis: the origin, signed normal and in-plane orientation also matter. A practical default to evaluate is to derive the frame from the source/instance coordinate frame by projecting its origin and designated axis onto the face. Offer explicit datum, origin, direction and flip when needed. Where continuity depends on capturing an initial frame, its relationship to a stable feature or datum must be reproducible from the model or explicitly persisted; an invisible in-memory first choice is not enough, and silently rewriting the model or a sidecar needs its own product decision. A dynamic face query may intentionally choose a different face; it does not promise identity continuity.

Do not recalculate a fresh arbitrary axis or centroid on each rebuild: `PlaneGeom::from_normal` in the pinned code changes its axis rule at a threshold, so a small normal change can rotate the resulting frame substantially; a centroid can move after an unrelated cut. When the designated axis is nearly parallel to the face normal, do not silently switch to another axis across edits: use a documented stable choice or report the degeneracy and a useful alternative. Define behavior for rotated or reflected instances, nonuniform scales and singular transforms. [Pinned face-anchor design](../../../../vendor/solidcraft/crates/doc/src/face_anchor.rs), [frame fallback](../../../../vendor/solidcraft/crates/geom/src/plane.rs).

Projection is an associative input to the sketch, separate from a constraint on authored geometry. The contract must define source selection, target frame, projection direction, curve representation and tolerance; it need not make the author spell out every ordinary choice. Candidate defaults are orthogonal projection along the support normal, reference/construction geometry, exact supported curves and the project tolerance, with explicit overrides. Distinguish projection from section/intersection. A source edge that collapses to a point, yields multiple curves, is unavailable, or can only be approximated needs an explicit result. Whether projected geometry participates in a profile is an explicit authoring choice. Recompute it when its dependencies change. Do not use the viewer mesh as source geometry.

SolidCraft's document layer already contains sketch-plane edge projection, but can fall back to fitted mesh polylines. Treat this as useful prior art, not a silently exact bridge. An API may support approximation with an explicit tolerance and status; an identity-backed exact constraint must not silently substitute it.

Constraints describe relationships among authored and projected entities: coincidence, point-on-curve, horizontal/vertical, tangency and dimensions are candidates. The solver should report degrees of freedom, residuals, redundancy/conflicts, nonconvergence and branch changes as available. A fully constrained system can still have multiple discrete solutions; an underconstrained one can have a useful initial state. Decide the build policy for each explicitly rather than equating solver success with unique intent. Initial guesses and branch selection must be reproducible from source or explicitly persisted state; a warm cache must not be the sole reason one branch is selected over another. Stale last-good geometry may be shown for recovery but must not masquerade as the new result. An example: a point constrained to be 5 mm from an infinite projected line can be on either side and can still slide along it; add a side and an along-line constraint when the author needs a unique placement.

A practical candidate policy is to allow underconstrained sketches when authored initial geometry supplies a reproducible solution, report remaining degrees of freedom, and offer strict mode for models that require full constraint. Avoid silently dropping redundant constraints. Refuse an unaccepted branch flip when detected, while acknowledging that the current solver's diagnostics have not been shown to detect every possible branch change.

The pinned sketch solver's `Failed` status can cover both inconsistency and failure to converge, so do not claim which occurred without independent evidence. Its status-only analysis does not perform full degrees-of-freedom analysis. Profile search can explicitly be incomplete and uses endpoint tolerances; a valid production profile needs a complete accepted search and kernel validation, not merely an apparently closed display.

Profile selection and extrusion require closed, valid loops with clear treatment of holes, self-intersections, tolerances and multiple regions. Extrusion direction, distance and union/cut/standalone behavior must be explicit. Resolve the host, projections, sketch solve and extrusion in dependency order, detect cycles, and leave the previous preview intact when any stage fails.

## Existing capabilities and constraints

- `solidcore_ops::prism::extrude_planar_regions` provides planar region extrusion. `prism::planar_edges` is a limited exact planar-edge reader, not a general projection solution. Other projection APIs must be checked for approximation and trimming behavior before use.
- The pinned `solidcraft-sketch` crate includes a Rust constraint solver, branch/DOF diagnostics and profile detection. Its dependency footprint and behavior have not been validated in SolidRecipe. Its links can be resolved by name but have point-based fallback and can retain stale geometry or remap/drop sketch constraints; the SolidRecipe adapter must not silently adopt those policies.
- Existing persistent provenance supports tested cases but does not certify all generated entities or missing descendants. The scoped callback-failure audit observes handler/placement failures that reach it, not omitted notifications. Do not turn an untracked result into a proven generated or deleted entity.
- Python builds graph descriptions. Rust owns authoritative execution, geometry and solving; the viewer renders a mesh for inspection. Generated queries, sketch dependencies and instance paths must be included in validation, cache keys and failure reporting.
- The current graph is recursively serialized, with process-local occurrence tokens for sharing; validation, cache keys and reachable-node traversal explicitly enumerate the current child fields. New query, support and projection inputs must not be omitted from any of these paths. A possible evolution is to normalize existing trees into a typed internal DAG, with explicit ports, cycle detection and cache keys that include all semantic scopes and inputs. A compact node table is an option, not a requirement for a particular file format. Graph-local node identity, geometry-equivalence cache keys and persistent feature identities serve different purposes.

## Alternatives to compare

1. **Declarative query:** retain criteria in the graph and evaluate against each rebuilt body. Natural for reusable sets and agent-authored intent; requires a typed query contract and explicit treatment of unknown candidates.
2. **Eager snapshot selection:** inspect a concrete body and manipulate a collection of its entities. Convenient for exploration and viewer selections; scoped handles become stale when the body changes.
3. **Hybrid:** use a declarative query for operations, provide snapshot inspection and explicit promotion to a persistent reference when lineage supports it. This is the current leading hypothesis, not a decision.

The hybrid is the leading hypothesis because a model author can express a reusable set without handling indexes, while a viewer or agent can inspect current matches and bind a particular proven entity when continuity matters. Its costs are an explicit query schema, revision-scoped snapshots and lineage-aware binding. A purely declarative design is simpler initially but still needs diagnostic inspection; an eager-only design is pleasant in Python but cannot serialize selection intent across a rebuilt Rust graph without additional rules.

## Two worked design exercises

These examples show desired behavior, not actual Python APIs. Names and exact syntax are intentionally unsettled.

**Boolean edge subset.** Start with a larger solid and a smaller intersecting tool. Subtract the tool. Ask for edges on the resulting interface between those two immediate operand occurrences, then filter to edges wholly on one authored side of a datum plane. Apply a fillet to the resulting set. If the chosen side is expected to contain two edges, an optional count assertion can detect a changed count. A known crossing edge is a non-match for a whole-side predicate. If one candidate's origin or side cannot be established, report incomplete instead of returning a deceptively clean set. A `created_by(cut)` query would have different semantics from an interface query and might exclude inherited contact edges.

**Constrained profile on a face.** Pick one planar face of a body through a query or a persistent reference. Establish a sketch frame using a documented default or explicit datum anchor and axis. Project a selected straight external edge into that frame as a nondegenerate reference line. Draw a circle; constrain its center to a signed 5 mm offset from the infinite line, constrain its position along the line relative to an explicit anchor, and constrain the radius. Select the closed circle profile and cut it through the host. On rebuild, resolve the host and source, reproject, solve, validate the profile, and cut. A moved source edge updates the circle; an unavailable or split source, an ambiguous side, a degenerate projection, an unaccepted solver branch, or an invalid profile must report its own failure and leave the last successful preview available. The exact APIs and default-frame policy remain open.

For sketch solving, compare the pinned Rust solver with alternatives only after checking its actual constraint coverage, numerical behavior, licensing and dependency footprint. The solver is a component, not the owner of SolidRecipe's graph, link resolution, identity or error policy.

## Evidence to gather and decision tests

- Two intersecting solids with several intersection edges: select a subset and fillet it; vary dimensions, operand order, instances and contact/coincident cases. Require that unknown provenance cannot disappear from a supposedly complete set.
- A cylindrical and an irregular or curved shape: query faces and edges without primitive-specific role names. Include ties, seams, transformed instances, closed curves and nonplanar normals.
- A profile on a translated/rotated/reflected planar face: project a source edge, constrain a profile against it, extrude/cut, then edit the source. Check frame continuity, projection, solver branch, resulting volume and cache invalidation.
- Negative cases: split/merged/missing references; ambiguous query; stale snapshot; wrong body; unsupported projection; closed or degenerate edge split; solver conflict/nonconvergence; open/self-crossing profile; graph cycle; failed operation leaves previous preview usable.
- Resource and reproducibility checks: verify dependency licenses, pinned revisions and clean reconstruction. Reuse the existing Rust target; remove task-owned temporary artifacts and do not claim unmeasured performance or disk cost.

## Possible delivery order

These are candidate slices, not a commitment to defer a user's workflow indefinitely. Each slice should demonstrate a real model through Python and the CLI/viewer, include failed-rebuild recovery, and keep other workstreams moving where independent.

1. **General geometric queries and group blends.** Query live result faces/edges by supported geometry, position and set relationships; pass a complete selected set to the actual body's ordered blend. Demonstrate a parameterized group fillet on a box and a supported non-box. Include ties, zero/multiple matches, wrong scope, unsupported curves and cache recovery. This slice does not claim Boolean construction lineage.
2. **Profile-defined cut.** Define a plane and closed line/circle profile, extrude it with the existing planar-region operation and subtract it. Demonstrate a parameterized through-hole and validate closed loops, holes, invalid profiles, resulting volume and rebuilds. This can test the geometry pipeline before a general constraint solver is adopted.
3. **Face-attached constrained profile.** Resolve a supported planar face and a source edge by explicit dynamic criteria or a proven reference. Construct a reproducible frame; project an exact supported straight edge; solve a circle constrained relative to it; select a complete closed profile; extrude and cut. Demonstrate a transformed face and parameter edit through the real entry point. Multi-source graph dependencies, cache invalidation, branch/DoF diagnostics and failed rebuild behavior belong in this slice, not as deferred polish.
4. **Construction and provenance queries.** After relevant kernel paths have an auditable completeness contract, select the requested subset of the two-solid interface and fillet the group. Cover coincident and tangent cases, untracked contributors, reused instances, operand order and transforms. A count assertion alone is not a completeness certificate.
5. **Subdivision and partial blend.** Add transactional splitting with actual child-handle mapping and explicit location modes. Test straight and circular cases, orientation and failure. Separately establish whether a blend can terminate at a split; a valid split can be useful even if the kernel requires a further feature for a partial fillet.

An attached sketch does not always require a durable topological identity: an explicitly geometric query may reselect the current face on each rebuild and fail on missing, tied or unsupported results. That is a different contract from following the same face through an edit. The implementation should make that choice understandable rather than requiring every ordinary sketch to supply a persistent ID.

## References

- [Onshape: queries and modeling context](https://cad.onshape.com/FsDoc/modeling.html) and [standard library queries and split operations](https://cad.onshape.com/FsDoc/library.html): declarative query semantics and explicit topology operations.
- [CadQuery selector documentation](https://cadquery.readthedocs.io/en/latest/selectors.html): composable geometric selectors and documented nonplanar-face caveats.
- [build123d topology selection](https://build123d.readthedocs.io/en/stable/topology_selection.html): operation results, topology ownership and query context.
- [Interactive Programming for Parametric CAD](https://onlinelibrary.wiley.com/doi/10.1111/cgf.14046): selection predicates and synthesizing queries from examples.
- [BRepQL](https://www.sciencedirect.com/science/article/abs/pii/S0166361524001350): composable topological search; the publisher abstract was available, not the full paper.
- [Kripac, persistent topological naming](https://www.sciencedirect.com/science/article/pii/S0010448596000401) and [Wang and Nnaji, semantic IDs](https://msse.gatech.edu/publication/JCAD_PID_wang.pdf): continuity across model reevaluation.
- [FreeCAD: topological naming problem](https://github.com/FreeCAD/FreeCAD-documentation/blob/main/wiki/Topological_naming_problem.md?plain=1): broken-reference reporting, candidate repair and limits of automatic resolution.
- [FreeCAD: Sketcher solver messages](https://github.com/FreeCAD/FreeCAD-documentation/blob/main/wiki/Sketcher_Dialog.md) and [SolveSpace: constraints](https://solvespace.com/constraints.pl): solver diagnostics and multiple solutions.
