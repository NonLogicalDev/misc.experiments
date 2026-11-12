# Topology-aware wire rendering

## Outcome

Render selectable B-rep edges with consistent apparent screen-space width, clear hover and selection states, and correct hiding by unrelated surfaces. Preserve face selection, model parameters, the orientation gizmo and the user's running preview. Validate against the adapter and targeted geometric cases, including close occluders and silhouettes.

## Integration

- The current viewer overlays independently tessellated edge polylines on shaded faces. Depth tests can clip portions of their wide screen-space strokes; arbitrary depth bias can reveal hidden lines.
- The user wants a real wireframe fix informed by research, including the actual B-rep edges rather than triangulation diagonals. The [research and prior diagnostics](../../_owner/docs/cad-edge-rendering-research.md) document why a simple offset or face-ID comparison alone is insufficient.
- Candidate integrated model: preserve explicit B-rep boundary ownership from tessellation through preview to face rendering. Shade certified boundary segments as part of the face; separately handle silhouettes and retain a clearly identified fallback when mapping is incomplete. Selection remains revision-scoped and uses the same record as the body.
- Open proof obligations include per-side metadata and coverage, line width at silhouettes, hidden and partly hidden edges, overlapping edges, seams, poles, coincident geometry, face winding, DPR and zoom, and consistent hover and selection. Do not silently label unsupported topology as complete or claim a verified fix before a browser comparison.
- Resource constraint: reuse the existing Rust target, avoid duplicate build trees, and clean task-owned experimental artifacts. Keep the current preview accessible until the replacement has passed checks.

## Current result

- Certified B-rep segments use face-boundary shading and a separate silhouette pass; edges without complete, two-face mappings retain ordinary outlines. Hover and selection remain available for both paths.
- The adapter is open at http://127.0.0.1:8770/ with the replacement build. Restarting created a new preview session and cleared its previous selection; both supplied selections are recorded in the [selection library](../../_owner/docs/selection-library.md).
- This is a practical raster renderer, not exact hidden-line removal. Very close and subpixel occlusion and ambiguous local fallback cases remain approximate; two adapter edges use the ordinary outline fallback.

## Work log

- 2026-11-11: Validated the replacement in the browser and restarted the live viewer. Four CLI selection tests, the preview integration test, frontend lint, TypeScript and production build, and provenance preparation passed. Controlled shader and allocation failures restored ordinary outlines. Eligibility-computation exceptions also fall back. The temporary test servers were stopped; the existing Rust target was reused.
- 2026-11-11: Kernel boundary mapping and same-record preview transport are implemented with explicit per-face completeness and fallback. A real box test and an unsupported-cylinder test passed. A separately launched default adapter preview reported 23 of 25 faces complete, 65 of 67 edges represented, and all six edges from the user's two selections mapped on both adjacent certified faces; 302 labeled sides matched sampled edge segments and face adjacency. This is snapshot-specific evidence. The temporary preview was stopped. A controlled face-boundary shader experiment measured a selected shared edge at approximately 3.5 CSS px, a silhouette at 1.5 px without the exterior pass and 3.0 px with it at DPR 2; the exterior pass and general occlusion remain under evaluation.
- 2026-11-11: User directed implementation after research and controlled tests ruled out treating a larger bias or a simple face-ID comparison as a proven solution. Work started in parallel; no new behavior has yet been verified.
