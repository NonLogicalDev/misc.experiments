# Repository composition

## Goal

Replace the special upstream base with ordered `git-clone` operations and allow a composed workspace to contain multiple repositories, including a clone at the workspace root. [Owners](../../OWNERS.md).

## Scope and completion

- [ ] Define repository-neutral configuration, paths, clone pins and operation behavior.
- [ ] Implement composition and relevant patch, overlay, commit and failure handling across repositories.
- [ ] Address legacy format and commands explicitly; preserve user data and provide a migration path where feasible.
- [ ] Validate with local Git fixtures, multiple repositories, root and nested paths, failure recovery, and real CLI commands.
- [ ] Document configuration and decisions; checkpoint locally without publishing.

## Current state

Active. User requested multiple repositories and a `git-clone` operation with a relative destination; an empty path denotes the workspace root. The commit behavior for changes spanning repositories is pending user input. Do independent inspection and design while waiting; do not implement that dependent behavior until resolved.

## Work log

- 2026-11-11: Started after user steering; verified current owner and clean checkout at `35f0928`. Previous manifest plan and local commits are preserved. Next: inspect repository assumptions and design an implementation.

## Workers

- /root/model: active, read-only analysis of repository model and schema.
- /root/workflow: active, read-only analysis of capture and recovery.
