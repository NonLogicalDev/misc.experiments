# Manifest operations

## Purpose and scope

Implement the user's approved `layer.toml` design: `[vcs] commit-msg`, ordered `[[operation]]` entries with `[operation.patch]` and `[operation.overlay]`, one generated commit per layer, and a migration path for existing `COMMIT_EDITMSG`, `patch`, and `overlay/` layers. Preserve patch and overlay conflict handling and exact commit messages. Keep legacy layers usable during transition. [Owners](../../OWNERS.md).

## Completion criteria

- [x] Parse and validate manifests safely, preserve operation order, and apply supported operations without losing conflict recovery.
- [x] Capture and refresh write manifests, preserve accepted trees and commit messages, and support legacy inputs.
- [x] Provide a safe migration command for legacy layers; prevent partial or silent data loss.
- [x] Document usage and verify unit, integration, and real CLI workflows.

## Current state

Status: completed. Manifest operations execute in order; legacy patch and overlay remain a combined step. Interrupted manifest advances persist progress and require abort when an operation outcome is ambiguous.

## Work log

- 2026-11-11: User approved the design and asked for Tasker_Stream under this project. Created the owner plan before implementation. Base: [worktree inventory](../../_owner/state/worktrees.md). Next: implement and validate in isolated working copies, then integrate.

## Assignments

- /root/manifest: completed; integration tests for arbitrary ordered operations in the isolated copy.
- /root/review_design: completed; implement resumable upstream operation state and recovery tests in the isolated copy.
- Owner: integrate capture, execution, CLI, documentation, and final verification.

- 2026-11-11: Checkpointed the initial plan in `a9e631cae62df196dd1b656a3389506a8165a12c`. Work is in `/private/tmp/layerctl-manifest-work`; local and temporary storage survival on host replacement is unverified. Manifest and migration work is underway; the user is choosing the first release's operation-order scope because arbitrary sequences require new conflict-recovery state.

- 2026-11-11: User chose arbitrary ordered operations. Implement per-operation execution and durable upstream recovery state; never commit an unresolved operation or silently skip later operations. Preserve legacy combined patch/overlay behavior and verify conflicts after restart. The initial restricted-order draft is provisional and will be replaced.

- 2026-11-11: Manifest definitions are loaded and legacy layers can migrate. The first draft passed the Go suite and a disposable CLI migration/replay; it has been copied into the checkout as unfinished work. User chose arbitrary operation order; the draft execution restriction is being replaced. Owner implements sequential operations; /root/review_design owns restart-safe upstream recovery; /root/manifest owns ordered-operation integration tests.

- 2026-11-11: Saved the passing migration draft in local commit `e001b8a9438826f207afeb22cc0399c5df44e453`. It deliberately does not yet implement the user's chosen arbitrary ordering. Ordered operation replay now passes focused tests in the temporary work copy; durable conflict recovery is in progress.

- 2026-11-11: Ordered replay and restart-safe recovery are implemented in the temporary work copy. The complete Go suite passed there; focused tests cover ordered same-file patches, overlay then patch, conflict continuation, changed layer definitions, layer-sequence changes, invalid state, and commit-message verification. Next: integrate into the checkout, verify there, review, and checkpoint.

## Validation and handoff

- `go test ./... -count=1` passed in the actual checkout with Go 1.26.10. One upstream empty-symlink test skips on this filesystem.
- Disposable CLI smoke test passed: legacy check, migration, manifest check, projection replay, exact commit message, and projection cleanup.
- Ordered operation tests cover repeated same-file patches, overlay then patch, and one commit. Recovery tests cover restart after conflict, remaining operations, changed definitions, changed layer sequence, invalid state, and message verification.
- `plan.py doctor` reported zero errors and warnings. Implementation checkpoint: `a65ce88fad31098d7d4349da4613ef0fe2e7d820`, local on this Mac. No push requested for this implementation.
