# Viewer

## Goal

Provide an interactive viewer for code-driven CAD models, with the geometry core remaining authoritative.

## Current state

- Status: initial live viewer, in-process preview, parameters and saved presets implemented.
- [React Three Fiber migration](completed/plan-01%20Migrate%20viewer%20to%20React%20Three%20Fiber.md).
- [Initial CLI and live viewer](completed/plan-02%20Connect%20CLI%20and%20live%20viewer.md): historical record; its subprocess and `uv` runtime notes were superseded.
- [In-process preview and parameters](completed/plan-03%20In-process%20preview%20and%20parameters.md): current architecture and verification.
- [Topology-aware wire rendering](active/plan-04%20Topology-aware%20wire%20rendering.md): active implementation and verification of consistent, occlusion-aware B-rep edge shading.
- Future work: exact CAD selection and measurement in the viewer; ordinary Python imports are not watched. Modeling and topology work is tracked in [its own domain](../theme-002-modeling/EXEC_STATE.md).
