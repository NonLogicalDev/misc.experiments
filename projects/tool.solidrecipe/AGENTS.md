# solidrecipe project guidance

Read `docs/plans/MEMORY.md` before substantive project work and use the plans under `docs/plans/`. Check `docs/plans/OWNERS.md` before changing owner state. Honor current user instructions and preserve unrelated changes.

solidrecipe is file-first and agent-first. Models are code and dependency graphs; Python is the first language interface. The core, CLI, and viewer are separate. SolidCore is the current B-rep kernel under evaluation; display meshes are not exact geometry.

Maintain a high density of useful documentation comments and inline comments across the codebase. Document public interfaces, data ownership, invariants, control flow, failure and recovery behavior, and the reasons behind non-obvious choices. Keep comments accurate as code changes; explain intent and constraints instead of repeating syntax.

Use `make format`, `make format-check`, `make lint`, and `make check` for project tooling. Checkpoint meaningful task-owned changes locally using the project Git workflow; do not push or publish unless asked.

In Python model examples, use `import solidrecipe as sr` and qualify API calls with `sr.`.
