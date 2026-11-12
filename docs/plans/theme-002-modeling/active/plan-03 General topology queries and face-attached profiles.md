# General topology queries and face-attached profiles

## Outcome

Design a general way to query faces and edges of arbitrary shapes, use sets or persistent references in modeling operations, subdivide edges, and construct a 2D profile on a face with constraints to projected geometry. Keep the design file-first, graph-based, in-process and usable by both people and agents. [Owners](../../OWNERS.md).

## Status and scope

- Status: active. The requested planning interval produced a working design for discussion; implementation dependent on this design remains paused while the model and priorities are reviewed.
- The intended result is a reviewable design with alternatives, concrete examples, research, failure behavior and a staged path. API examples are proposals, not existing functionality.
- [Working design and research](../../_owner/docs/topology-queries-and-attached-profiles.md) records the competing models, examples and open decisions.
- Preserve the unfinished [topology identity work](plan-02%20Persistent%20topology%20identity.md), its checkpoints, and the [untested edge-split draft](../../_owner/artifacts/UNTESTED-ordered-edge-split-draft.patch). Do not infer that a query or a fingerprint proves persistent identity.

## Starting evidence

- SolidRecipe evaluates a Python-authored graph in Rust through SolidCore. Existing inspection and cached results pair a body with its record and entity order; displayed meshes are not authoritative geometry.
- Named boxes and the draft named-cylinder identities cover limited semantic origins. Boolean and blend histories remain incomplete for some generated, deleted and coincident entities.
- The pinned SolidCraft checkout includes a Rust sketch solver and profile detection in `vendor/solidcraft/crates/sketch/`; its fit, numerical behavior and dependency cost need validation. Its existing point-based model links cannot automatically satisfy the established no-silent-retargeting rule.
- SolidCore exposes planar-region extrusion and other curve/face operations, but the project does not yet expose sketches, profiles or extrusion. Sketch projection and constraints must be dependency graph inputs, not copied preview geometry.

## Questions and scenarios

- Query an arbitrary shape's faces by geometry, adjacency, provenance, region or a combination; apply an operation to all matches or require an explicit count.
- Boolean a larger and smaller solid, select a subset of their intersection edges, and fillet the set. Differentiate a dynamic query from a request to track the same edge across changes.
- Subdivide an edge at explicit locations and refer to its children. Distinguish curve parameters from physical lengths and test whether the kernel can stop a fillet at the split.
- Attach a profile to a planar face, project external geometry, constrain the profile against it, and extrude or cut. Specify the face reference, local frame, projections, solver behavior, branch choice, units and failure recovery.
- Expose stable identity where supported, current-revision inspection labels, and fingerprints or evidence for human/model-assisted recovery. A candidate match is not proof of identity.

## Investigations

- `/root/identity_design`: compared query and topology selection models in primary documentation and literature, including ordering and ambiguity.
- `/root/provenance_review`: researched constraint solvers, projected geometry, frames and solve failures; assessed the pinned sketch crate and alternatives.
- `/root/blend_check`: inspected actual SolidCore and SolidRecipe interfaces, mapped concrete examples to viable increments, and identified constraints and missing proofs.
- `/root`: integrated evidence, compared product models, developed examples and acceptance criteria, and reviewed the design.

## Work log

- 2026-11-11: Started a dedicated planning interval at the user's direction. Existing work is checkpointed at `b417d18`; vendor source remains prepared by the tracked patches. No design-dependent implementation is being started during planning.
- 2026-11-11: The working design now compares declarative queries, snapshot inspection and persistent references; covers ambiguous/unknown selection, repair, subdivision, a face-attached projected profile, solver and frame policies, and possible user-visible increments. Independent reviewers checked it against the user's examples and current kernel source. The SolidCraft solver is a candidate, not yet evaluated in SolidRecipe. No code or build was run during this planning interval; prepare script and local design links were checked, and vendor changes remain the intentional tracked-patch state.
