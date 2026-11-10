# Migrate viewer to React Three Fiber

## Purpose

Use React Three Fiber and Drei controls for the React viewer while preserving local OBJ loading and camera interaction.

## Scope

- Replace imperative Three.js rendering with declarative scene components and on-demand rendering.
- Preserve mesh loading, framing, orbit, pan, zoom, and useful error reporting.
- Keep display meshes separate from SolidCore geometry; do not claim exact CAD measurement.
- Verify the build and browser behavior, including a generated example and invalid input.

## Work log

- 2026-11-10: User requested the migration and Tasker_Stream records in `docs/plans`. A staged implementation builds; browser validation and application to the project remain in progress.

- 2026-11-10: Staged R3F viewer built; browser verified model loading, orbit, invalid-input handling, and loading the model again.
