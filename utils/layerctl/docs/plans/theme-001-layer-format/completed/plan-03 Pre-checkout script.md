# Pre-checkout script

## Goal

Allow `git-clone` to run a trusted `pre-checkout-script` against an isolated bare Git repository before materialization. The script prints a full commit or tree SHA to stdout; a returned commit becomes the imported parent, while a returned tree uses the fetched commit as its parent. A clone with no `dir` targets the workspace root, as does `dir = ""`. [Owners](../../OWNERS.md).

## Scope and validation

- [x] Define script path, context, SHA validation, ordering with `pre-checkout-patch`, failure handling, and recovery fingerprints.
- [x] Implement the manifest, isolated bare-repository hook and optional clone `dir`; preserve existing definitions and imported ancestry.
- [x] Verify clone, patch-plus-script ordering, SHA types and failures, refresh, recovery, scripts with support files, and omitted/explicit `dir` through focused tests and the CLI.
- [x] Document the interface and script side effects, review the integration, and checkpoint locally without publishing.

## Assignments

- /root/model: completed manifest parsing, optional `dir`, refresh, recovery fingerprints and focused tests.
- /root/projection: completed bare-repository hook execution, output selection and focused tests.
- /root/integration_review: completed independent design review and staging regression verification.
- Owner: coordinate interface, integrate CLI/projection, document and verify the end-to-end behavior.

## Decisions

- `pre-checkout-script` is an executable path relative to its layer directory. Run it after `pre-checkout-patch` when both are configured.
- Run the hook in an isolated bare source repository. Provide its source commit and prepared tree plus layer and projection context through `LAYERCTL_*` variables. Stdout carries only the returned full commit/tree SHA; diagnostics go to stderr. Scripts are trusted and can have external side effects, including when `check` or refresh replays them.
- The existing single-line `dir` format and `pre-checkout-patch` continue to work; omission and an explicit empty string have identical root behavior.

- User requested operation implementations in `internal/operations/*.go` and filenames ordered from least to most specific. Move clone, script, patch and overlay execution there, retain commit capture/recovery behavior, and rename touched related files to group by category. /root/model completed patch/overlay extraction and layercommit integration. /root/projection completed clone/script moves and hook path revalidation. The owner integrated dispatch and verified the results.

- Independent review reproduced a staging escape on case-insensitive filesystems when a source tree contains a symlink and a differently cased child path. Fix clone staging to reject symlink parent components before writing, including ordinary clone and pre-checkout cases; add a regression and verify no external file is created. Revalidate hook paths immediately before execution after fetch.

- Full Go suite passed in the isolated implementation copy after moving operations. Go integration tests verified patch-before-script ordering. CLI smoke tests verified tree and commit SHA output, optional root directory, refresh replay and nested-clone merge ancestry. The refactored CLI rebuilt Deluge from upstream SSH with the expected tree and parent. Clone staging now rejects case-folded symlink parents, and failed hooks cannot be skipped via conflict recovery. The changes were integrated into the actual checkout and the full Go suite passed there. A final case-insensitive Deluge projection and `check` replay also reproduced its expected firmware tree and source parent.
