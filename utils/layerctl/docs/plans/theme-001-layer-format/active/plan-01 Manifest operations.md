# Manifest operations

## Purpose and scope

Implement the user's approved `layer.toml` design: `[vcs] commit-msg`, ordered `[[operation]]` entries with `[operation.patch]` and `[operation.overlay]`, one generated commit per layer, and a migration path for existing `COMMIT_EDITMSG`, `patch`, and `overlay/` layers. Preserve patch and overlay conflict handling and exact commit messages. Keep legacy layers usable during transition. [Owners](../../OWNERS.md).

## Completion criteria

- [ ] Parse and validate manifests safely, preserve operation order, and apply supported operations without losing conflict recovery.
- [ ] Capture and refresh write manifests, preserve accepted trees and commit messages, and support legacy inputs.
- [ ] Provide a safe migration command for legacy layers; prevent partial or silent data loss.
- [ ] Document usage and verify unit, integration, and real CLI workflows.

## Current state

Status: active. The existing implementation combines patch and overlay for a single three-way Git application. The operation model must preserve recoverable conflict behavior, especially staged overlay additions. Determine and document any ordering restrictions from the implementation rather than silently changing semantics.

## Work log

- 2026-11-11: User approved the design and asked for Tasker_Stream under this project. Created the owner plan before implementation. Base: [worktree inventory](../../_owner/state/worktrees.md). Next: implement and validate in isolated working copies, then integrate.

## Assignments

- /root/manifest: active; manifest parsing and definition validation in an isolated copy.
- /root/review_design: active; independent review of migration and ordering semantics.
- Owner: integrate capture, execution, CLI, documentation, and final verification.
