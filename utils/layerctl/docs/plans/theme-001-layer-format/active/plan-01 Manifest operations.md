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

- /root/manifest: active; integration tests for arbitrary ordered operations in the isolated copy.
- /root/review_design: active; implement resumable upstream operation state and recovery tests in the isolated copy.
- Owner: integrate capture, execution, CLI, documentation, and final verification.

- 2026-11-11: Checkpointed the initial plan in `a9e631cae62df196dd1b656a3389506a8165a12c`. Work is in `/private/tmp/layerctl-manifest-work`; local and temporary storage survival on host replacement is unverified. Manifest and migration work is underway; the user is choosing the first release's operation-order scope because arbitrary sequences require new conflict-recovery state.

- 2026-11-11: User chose arbitrary ordered operations. Implement per-operation execution and durable upstream recovery state; never commit an unresolved operation or silently skip later operations. Preserve legacy combined patch/overlay behavior and verify conflicts after restart. The initial restricted-order draft is provisional and will be replaced.

- 2026-11-11: Manifest definitions are loaded and legacy layers can migrate. The first draft passed the Go suite and a disposable CLI migration/replay; it has been copied into the checkout as unfinished work. User chose arbitrary operation order; the draft execution restriction is being replaced. Owner implements sequential operations; /root/review_design owns restart-safe upstream recovery; /root/manifest owns ordered-operation integration tests.
