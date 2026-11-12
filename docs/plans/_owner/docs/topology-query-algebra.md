# Topology query algebra: iterations and evidence

**Working research, 2026-11-11.** This supports the [topology query design](topology-queries-and-attached-profiles.md). The terms below describe capabilities, not a final Python API or implemented behavior.

The later [construction-based query study](construction-query-study.md) applies this algebra to actual selections, operation history, curved and Boolean cases, and counterexamples. It supersedes any implication here that shape-specific roles are universal or that the current SolidRecipe provenance report is the intended limit of the design.

## What can be proved

There is no meaningful absolute smallest list of verbs with maximum descriptive power without first defining the allowed inputs, operations and cost of a verb. An all-purpose programming-language expression could hide the entire problem in one verb. Instead, fix a finite, revision-scoped set of topology entities and a declared vocabulary of relations and properties. Then ask what a query can describe using those facts.

For that model, a small core can express every query in the domain-independent first-order relational fragment. This is the established equivalence between relational algebra and safe relational calculus, applied to a CAD topology schema. It is a precise baseline, not proof of every conceivable modeling intention. [Codd, relational completeness](https://db.dobo.sk/wp-content/uploads/2015/11/Codd_1972_Relational_Completeness.pdf); [Maier, query systems](https://web.cecs.pdx.edu/~maier/TheoryBook/MAIER/C10.pdf).

## Three iterations

1. **Entity sets and unary filters.** Choose faces or edges, filter by geometry or provenance, and combine sets. This covers many useful cases but independent adjacency checks do not express all relationships between witnesses. A single merged face with both operand origins can satisfy both checks, even if the author meant two distinct faces. A seam may use the same face twice.
2. **Add bound variables and quantification.** A condition can refer to an edge and two distinct incident faces at once. Bindings, equality, Boolean composition and `exists` let us express general correlations instead of creating a specialized fluent method for each pair of relationships. This covers the first-order fragment over the facts actually available.
3. **Add traversal and stress the boundary.** Arbitrarily long connected or tangent chains cannot generally be described by a fixed first-order expression. Add a general graph traversal or transitive closure, parameterized by the relationship to follow. Treat counting and measurement as explicit extensions, and test completeness and uncertainty independently of expressibility. [Libkin, finite model theory](https://www.cs.toronto.edu/~libkin/fmt/fmt.pdf).

## Candidate core

- **Choose a domain:** entities or uses of a stated type within a body, instance and evaluated revision.
- **Filter:** retain entities for which a composed predicate holds. Predicate expressions support equality, Boolean operations, typed relation and property tests, and bound variables.
- **Bind related entities:** `exists` ranges over an explicit typed domain and can refer to previously bound variables. Universal conditions can be expressed as absence of a counterexample when the universe and facts are complete.
- **Combine sets:** union, intersection and difference are useful surface operations. They do not each need to be independent primitives; this choice is about usability and a serializable expression representation.
- **Traverse:** follow a declared relationship for any number of steps, with explicit seed and inclusion rules. This is an extension beyond first-order queries; the step predicate may capture query parameters.
- **Measure and count:** expose supported numerical properties, comparisons and cardinality where the task requires them. A fixed number of distinct witnesses can be expressed with quantifiers; a general count or aggregate needs an explicit contract. Selection of extrema needs tie and precision rules.

Geometry, history, incidence and spatial relationships are typed facts or predicates, not a new chained method for every modeling workflow. They still need a documented vocabulary: compressing the language to `filter` does not create a plane-side test or make missing lineage available. Entity-use and orientation records may be necessary in addition to entity identities for seams and nonmanifold shapes.

## Proof sketch and assumptions

Assume complete finite typed domains, total relations and properties, explicit equality, and a query with a bounded tuple of free entity variables. Atomic facts translate to relation lookups. Conjunction translates to a join; disjunction to union after matching the same free-variable domains; negation to difference from the complete product domain; existential quantification to projection. By induction on formula structure, every formula in the stated fragment has a corresponding relational expression. Conversely, selection, product or join, projection, union and difference each have a first-order formula, so the relational operations do not exceed that fragment. Typed domain selection supplies the finite universe. This proof relies on correlated variable binding; independent unary filters alone are not enough.

The `traverse` extension expresses reachability for its supplied relation, including a connected edge chain. It does not make every possible geometric question or computational algorithm available. More powerful iteration has been studied separately: [Chandra and Harel, Computable Queries for Relational Data Bases](https://www.weizmann.ac.il/math/harel/sites/math.harel/files/users/user50/ComputableQueries.pdf) characterize a relational algebra extended with iteration under their formal model. Their result is not a claim that a particular CAD traversal implementation computes every modeling intent.

This proof assumes the schema already contains the facts in question. It does not establish that the kernel computes whole-curve relations, that numerical tolerances are adequate, that provenance is complete, that construction history survives a rebuild, or that a query selects the author's intended objects. Symmetric entities may be indistinguishable under all supplied facts. Extending the set of facts can increase descriptive power without changing the core syntax.

## Scenario checks

| Intent | Required expression or capability | Boundary |
| --- | --- | --- |
| Fillet part of a Boolean interface | Select edges with two distinct incident faces, one with verified stock origin and one with verified tool origin; combine with an explicit spatial condition. | An interface edge is not necessarily newly created. Origin completeness, immediate versus transitive sources, coincident contact, side, boundary and tolerance all need contracts. |
| Follow a tangent chain | Traverse incidence between edges while the supplied tangent predicate holds. | Requires an actual reliable tangent relation; a fixed number of neighbor checks is insufficient. |
| Find a face on an arbitrary body | Filter the face domain by supported geometry, relation, position or measurements; return all ties. | Curved faces do not have one global normal, and local sampling is not proof of a whole-face predicate. |
| Fillet a section of an edge | Select an edge, perform a split or partial blend, then select its result using the operation's lineage. | Queries do not create vertices. A successful split does not prove the kernel can stop a fillet there. |
| Attach a sketch and constrain it to projected geometry | Select a host and source, project into a defined frame, solve constraints, then extrude. | Projection, constraint solving and extrusion are graph operations, not query verbs. A dynamic query does not establish persistent identity. |
| Recover after topology changes | Inspect current candidates, their evidence and the original intent; explicitly repair a reference or query. | A snapshot index, a geometric hash or the expected match count cannot prove continuity. |

For the interface example, the condition is `exists f, g: f != g and incident(e, f) and incident(e, g) and origin(f, stock) and origin(g, tool)`. All three entities belong to the stated result scope. A separate condition defines which side of a plane contains the whole edge. If the desired meaning is instead edges newly created by a particular Boolean, add that specific history condition; do not assume it follows from adjacency. [build123d selection](https://build123d.readthedocs.io/en/stable/topology_selection.html); [Onshape query and split operations](https://cad.onshape.com/FsDoc/library.html).

## Incomplete evidence

The classical proof assumes complete facts. Real kernel evidence may be unknown. Evaluate predicates as true, false or unknown, with an explicit flag for whether enumeration is complete. For an existential condition, one proven witness is true; false requires a complete domain and all candidates proven false; otherwise it is unknown. Negation preserves unknown. A known-false condition can still exclude a candidate even when another condition is unknown.

One conservative implementation tracks definitely matching and possibly matching sets. For difference, the definite result is definite-left minus possible-right; the possible result is possible-left minus definite-right. These bounds can be conservative when predicates are correlated, so do not call them exact inference. Unknown entity enumeration requires separate reporting. A cardinality assertion must account for possible extra matches; even an exact count cannot prove that the same entities were selected after an edit.

This is a design requirement, not a claim that the current provenance implementation supplies the necessary completeness certificates. A modeling operation that needs a complete set must not silently drop possible matches; inspection may present them as candidates for repair.

## CAD research and implementation prior art

- [BRepQL: Query language for searching topological elements in B-rep models](https://doi.org/10.1016/j.compind.2024.104207) directly investigates anchored topological conditions and sequences of searches. The available abstract describes the approach but does not prove a minimal or complete vocabulary.
- [Interactive Programming for Parametric CAD](https://dzufferey.github.io/files/2020_Interactive_Programming_for_Parametric_CAD.pdf) studies composing and synthesizing selection predicates from examples. Agreement on examples is evidence, not proof that a query captures intent after all parameter changes.
- [Bidarra, Nyirenda and Bronsvoort, A Feature-Based Solution to the Persistent Naming Problem](https://graphics.tudelft.nl/~rafa/myPapers/jrnl-bidarra.CAD05.pdf) examines two edges between the same faces and uses a reference plane to distinguish an intersection. A later edit leaves multiple candidates on the same side, so the paper detects ambiguity and calls for repair. Its approach depends on feature ownership and restrictions on face merging; it is not an automatic guarantee for arbitrary imported geometry.
- [Wang and Nnaji, Geometry-based semantic ID](https://msse.gatech.edu/publication/JCAD_PID_wang.pdf) studies naming based on geometric construction and continuity. It addresses persistent reference, which is a different problem from describing a dynamic query.
- [Persistent identification using macro-parametrics](https://academic.oup.com/jcde/article/3/2/161/5743368) discusses ambiguity from splitting and merging and cross-system identification.
- [Onshape modeling queries](https://cad.onshape.com/FsDoc/modeling.html) and its [standard library](https://cad.onshape.com/FsDoc/library.html) provide a production comparison: queries are criteria evaluated in a modeling context; adjacency, history, set operations, tangent connectivity and actual edge splitting have distinct semantics.

## Open decisions

- Design a readable author-facing syntax and a serializable typed internal representation; the proof does not dictate Python syntax.
- Specify the minimum useful initial catalog of geometry, incidence and lineage facts, their tolerances and their ability to report unknown.
- Define whether traversal is a generic relation closure, a smaller constrained operation, or a kernel-supplied component relation; quantify the expressivity given up by restrictions.
- Validate the user scenarios against actual kernel evidence, including coincident contact, seams, merged faces, incomplete provenance, ties and rebuilds. No Rust compilation was needed for this research.
