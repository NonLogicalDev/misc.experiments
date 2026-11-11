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

Active. User requested multiple repositories and a `git-clone` operation with a relative destination; an empty path denotes the workspace root. User chose one commit for the whole workspace. User confirmed clone contents are composed as files into one resulting Git repository; source histories remain separate. A layer creates one workspace commit.

## Work log

- 2026-11-11: Started after user steering; verified current owner and clean checkout at `35f0928`. Previous manifest plan and local commits are preserved. Next: inspect repository assumptions and design an implementation.

## Workers

- /root/model: active, read-only analysis of repository model and schema.
- /root/workflow: active, read-only analysis of capture and recovery.

- 2026-11-11: User chose one commit for the whole workspace. Asked whether clone contents should be composed as files into one Git repository, because separate nested Git histories cannot be represented by a single normal commit. Existing `upstream.json` has no source URL, so migration cannot infer it safely.

- 2026-11-11: User confirmed source files should be composed into a single Git repository while source histories remain separate. Define clone destinations as workspace-relative, with empty string for root; avoid nested Git metadata and accidental gitlinks.

## Implementation assignments

- /root/model: active; extend manifest definitions and tests with `operation.git-clone` (`url`, `dir`, optional `ref`, `commit`, `depth`) without assuming a root repository.
- /root/workflow: active; implement clone materialization and source commit import into an owned workspace, with focused tests.
- Owner: integrate workspace projection, ordered execution, CLI, capture/recovery decisions, and end-to-end verification.

- 2026-11-11: User suggested merge commits. Investigating whether imported source commits should become additional parents of each layer commit, preserving ancestry while the composed tree places files at the requested destination. User confirmed that imported source commits become additional parents, preserving source ancestry in the composed workspace. An initial layer with one source has one parent; merge commits arise when there are multiple parents.

- 2026-11-11: User requested branch, commit, and history depth options for `git-clone`. A specified commit is an exact checkout; if a ref is also supplied, verify reachability and report when shallow history cannot establish it. Preserve imported Git ancestry as available at the selected depth.

- Pending independent projection and CLI architecture analysis for isolated object databases and shallow merge parents; current shared-object worktrees risk changing unrelated Git history boundaries.

- 2026-11-11: User replaced the `branch` option with `ref`, supporting branches, tags and other Git refs.

- 2026-11-11: Approved merge-parent model and ref/commit/depth options. Implementing isolated per-projection Git repositories to protect the definition checkout's object database and shallow boundaries. Existing single-repository mode stays available for existing definitions while the new mode removes special upstream and foundation assumptions. Record explicit limitations for combinations Git cannot safely represent.

- /root/projection: active; isolated projection lifecycle and merge-parent commits.

- Next: preserve clone operations and source merge parents when refreshing a composed layer; verify the rebuilt workspace tree and exact message before replacing a manifest.
