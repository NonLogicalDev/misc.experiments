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

- 2026-11-11: Composed projections must preserve conflict recovery without an upstream-specific command. Implement `projection continue` with persisted operation/parent state, owned workspace checks, definition fingerprints, and fail-closed handling of interrupted mutations.

- 2026-11-11: User added `layer.enabled` and `layer.depends-on`. Default enabled to true; dependencies name existing earlier enabled layers and are validated before composition. Disabled layers are skipped. Keep operation and history semantics intact.

- 2026-11-11: User requested a layerctl subcommand to generate a DOT graph of layers. Implement `layerctl graph` writing dependency edges and enabled/disabled layer status to stdout, without a Graphviz runtime dependency.

- 2026-11-11: User also requested Mermaid; `layerctl graph --format mermaid` will complement DOT. Projection bootstrap has a verified crash window before ownership metadata is saved; record recoverable intent and never delete an unverified workspace.

- 2026-11-11: User requested a script operation receiving `LAYERCTL_WORKTREE_DIR` and useful `LAYERCTL_*` context. Scripts are explicit trusted operations; run from the workspace, expose layer ID and paths, fail on nonzero exit, and stage resulting workspace changes for the layer commit. Preserve recovery safety and document that scripts can have external side effects.

## Current assignments

- /root/model: active, script manifest and runner, including refresh preservation.
- /root/projection: active, projection recovery and script integration.
- /root/workflow: active, DOT and Mermaid graph renderer.

- 2026-11-11: User requested a JJ mode for layerctl. Investigate how JJ changes and merge-parent history should be represented, validate against the installed JJ, and implement the agreed mode. User chose support for both Git and JJ modes. Evaluate a colocated JJ workspace so each generated Git layer commit is visible as a JJ change, preserving merge parents. Use Deluge conversion as an integration target after layerctl is ready.

- 2026-11-11: User selected both Git and JJ modes. Investigate `projection create --vcs git|jj` (Git default), preserve merge ancestry and layer descriptions, and validate actual JJ behavior without mutating existing repositories.

- 2026-11-11: User clarified that JJ mode can assume a Git-backed repository. Validate the actual colocated JJ workflow before committing to it.

- 2026-11-11: User requested `vcs` co-authors. Support `[vcs] co-authors` as a list of `Name <email>` values rendered as Git `Co-authored-by` commit trailers, preserving attribution in Git and Git-backed JJ. Validate and document message behavior.

- /root/model: active, co-author metadata and commit trailer handling.
- /root/workflow: active, Git-backed JJ workspace integration.
- /root/projection: pending, integrate JJ mode after its interface is verified.

- 2026-11-11: User confirmed layerctl is Git-centric for now and permits Git-native optimizations such as object sharing. Preserve isolated shallow boundaries and avoid optimizing away correctness.

- 2026-11-11: User dropped JJ mode for now. Keep layerctl Git-only; still inspect the JJ-based Deluge fork and convert its resulting history and changes after the tool is ready.

- 2026-11-11: User questioned `internal/upstream/cargo_lock.go`. Remove the Codex-specific Cargo.lock policy from generic and legacy checks; test that checking a legacy projection does not require that file.

- 2026-11-11: Git-only composition, merge parents, ref/commit/depth, enablement/dependencies, DOT/Mermaid graph, scripts, coauthors, conflict recovery, and legacy compatibility implemented in temporary copy. Full Go suite passed there after removing Codex Cargo lock policy. Next: integrate into checkout, inspect the diff, run full validation and CLI smoke before Deluge conversion.

- 2026-11-11: User requested a reusable skill at `skills/layerctl/`; write it from verified CLI behavior, validate it, and test retrieval in an isolated scenario.

- Independent review found that refreshing script-bearing manifests could discard operations and `layer add` could flatten merge ancestry. Preserve authored manifest operations for all composition refreshes and reject merge capture unless ancestry is explicitly represented; add regression tests before proceeding.

- 2026-11-11: Integrated the reviewed Git-only composition implementation and skill. Full Go suite, gofmt, skill validator and plan doctor passed. Real CLI smoke verified two merge parents, both graph formats, disabled/dependency metadata, script environment and assets, coauthors, stdout isolation and cleanup. One upstream empty-symlink case skips on this filesystem. Next: checkpoint locally, then assess Deluge conversion; do not publish.
