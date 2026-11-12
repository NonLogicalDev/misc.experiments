# Pre-checkout script

## Goal

Allow `git-clone` to run a trusted `pre-checkout-script` against an isolated bare Git repository before materialization. The script prints a full commit or tree SHA to stdout; a returned commit becomes the imported parent, while a returned tree uses the fetched commit as its parent. A clone with no `dir` targets the workspace root, as does `dir = ""`. [Owners](../../OWNERS.md).

## Scope and validation

- [ ] Define script path, context, SHA validation, ordering with `pre-checkout-patch`, failure handling, and recovery fingerprints.
- [ ] Implement the manifest, isolated bare-repository hook and optional clone `dir`; preserve existing definitions and imported ancestry.
- [ ] Verify clone, patch-plus-script ordering, SHA types and failures, refresh, recovery, scripts with support files, and omitted/explicit `dir` through focused tests and the CLI.
- [ ] Document the interface and script side effects, review the integration, and checkpoint locally without publishing.

## Assignments

- /root/model: active; manifest parsing, optional `dir`, refresh, recovery fingerprints and focused tests.
- /root/projection: active; bare-repository hook execution, output selection and focused tests.
- /root/integration_review: active; independent design and security review.
- Owner: coordinate interface, integrate CLI/projection, document and verify the end-to-end behavior.

## Decisions

- `pre-checkout-script` is an executable path relative to its layer directory. Run it after `pre-checkout-patch` when both are configured.
- Run the hook in an isolated bare source repository. Provide its source commit and prepared tree plus layer and projection context through `LAYERCTL_*` variables. Stdout carries only the returned full commit/tree SHA; diagnostics go to stderr. Scripts are trusted and can have external side effects, including when `check` or refresh replays them.
- The existing single-line `dir` format and `pre-checkout-patch` continue to work; omission and an explicit empty string have identical root behavior.
