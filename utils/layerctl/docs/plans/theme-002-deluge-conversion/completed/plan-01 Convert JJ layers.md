# Convert DelugeFirmware from JJ

## Goal

After layerctl is implemented and verified, carefully convert `https://github.com/NonLogicalDev/fork.DelugeFirmware` from its JJ-based approach to the new layerctl format. Preserve source data and provenance. Do not publish unless asked. [Owners](../../OWNERS.md).

## Completion criteria

- [x] Resolve the existing checkout or clone the requested repository at its configured project path; read applicable instructions and inspect its JJ/Git state.
- [x] Identify its base repositories, revisions, JJ stack, changes, and intended outputs without discarding work.
- [x] Capture an equivalent layerctl definition with traceable source and validate a clean reconstruction against the available published Git/JJ-derived state.
- [x] Document evidence and limitations, checkpoint locally, and preserve rollback material.

## Current state

Completed locally: layerctl was tested and checkpointed at `334770a513e65ebbe9c0cc63d2d1e72a842fa547`. The fork was cloned over SSH at `/Users/nonlogical/Projects/remote/github.com/NonLogicalDev/fork.DelugeFirmware`; its clean `nl/latest` checkout is at `2391b7cad4907843890d8b6c052651a77abd6bbf`. Preserve all refs and source history; do not publish.

- User dropped JJ mode in layerctl, but the requested Deluge conversion remains in scope. Inspect the fork and convert its JJ-based history to the Git-centric layer format without requiring a JJ-mode projection.

## Current assignments

- /root/model: completed read-only history and filesystem analysis; owner verified the 34-commit linear stack and source pins.
- /root/projection: completed read-only walkthrough analysis; owner verified the documented edit and refresh flow with a local fixture.
- Owner: completed integration, walkthrough, conversion, verification, and plan updates.

## Conversion evidence and next steps

- The source stack has 34 linear commits above fork `main` (`9e3132dc17070695b40f69bada5565a33ce428b4`). All advertised branches point into that history. Preserve every commit boundary and original SHA, author, message, and JJ change-id as provenance. `711d48340ddb9c42d65db6088434b4b9c2ba5e58` has an empty tree change and message; use a documented marker message rather than inventing its original message.
- The base has case-colliding directories. This Mac uses a case-insensitive checkout; use a temporary case-sensitive filesystem for a faithful source reconstruction, and verify every layer tree against its original commit. The checkout is a blob-filtered partial clone; lazily fetch required objects through the authorized SSH remote.
- The skill walkthrough was exercised against an isolated local Git fixture, including add, refresh, check, graph, and projection deletion. It explains that conflict resolutions do not automatically update definitions.

- The 35-layer temporary definition rebuilt successfully on a case-sensitive APFS image. Every layer tree equals its original tree, including final tree `cdc903646a5ff9a81a05225a346d17d16fe5ad31`; the workspace is clean and base source is the first layer commit parent. `layerctl check` is running on a fresh reconstruction. Next: create a local conversion branch without changing the original checkout and verify its definition contents.

- Full `layerctl check` passed with a fresh SSH rebuild. The 35-layer conversion, original metadata, branch tips, license, and rebuild instructions were committed as `5967d2e3e82e60a9739ffed2a9b34ec1c50bca8e` on the new local branch `layerctl-conversion` in the source fork. The original `nl/latest` checkout remains clean at `2391b7cad4907843890d8b6c052651a77abd6bbf`; remote refs are unchanged and nothing was pushed. The published Git refs are the available evidence; no unpushed JJ state was found in this fresh clone. Patch files preserve original whitespace, so generic `git diff --check` reports whitespace within patch payloads; changing that content would alter the source patches.

- Exposed the completed conversion in the clean linked worktree `/Users/nonlogical/Projects/remote/github.com/NonLogicalDev/fork.DelugeFirmware-layerctl`. The shared Git common directory is the original fork checkout. Unmounted the case-sensitive validation image and retained it in temporary storage.

- Added the generated Mermaid layer graph to the conversion README. Verified its contents exactly match `layerctl graph --format mermaid` and saved local checkpoint `7f7c7bdfd83dfc537972268a888b43c46d297053`.

- Declared Deluge dependencies using feature and patch-context evidence, retained the JJ change IDs and branch-tip provenance, converted commit messages to multiline TOML without changing their bytes, and regenerated the README graph. Saved local checkpoint `e8c71d7b103e95a050e51c0c759308e512f27038`. All 34 dependency closures replayed from an isolated base; three representative subsets and the full stack passed through layerctl, with all trees and original messages matching. These checks validate patch replay, not firmware compilation.
