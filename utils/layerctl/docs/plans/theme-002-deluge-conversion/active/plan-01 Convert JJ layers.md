# Convert DelugeFirmware from JJ

## Goal

After layerctl is implemented and verified, carefully convert `https://github.com/NonLogicalDev/fork.DelugeFirmware` from its JJ-based approach to the new layerctl format. Preserve source data and provenance. Do not publish unless asked. [Owners](../../OWNERS.md).

## Completion criteria

- [ ] Resolve the existing checkout or clone the requested repository at its configured project path; read applicable instructions and inspect its JJ/Git state.
- [ ] Identify its base repositories, revisions, JJ stack, changes, and intended outputs without discarding work.
- [ ] Capture an equivalent layerctl definition with traceable source and validate a clean reconstruction against the accepted JJ state.
- [ ] Document evidence and limitations, checkpoint locally, and preserve rollback material.

## Current state

Active: layerctl was tested and checkpointed at `334770a513e65ebbe9c0cc63d2d1e72a842fa547`. The fork was cloned over SSH at `/Users/nonlogical/Projects/remote/github.com/NonLogicalDev/fork.DelugeFirmware`; its clean `nl/latest` checkout is at `2391b7cad4907843890d8b6c052651a77abd6bbf`. Preserve all refs and source history; do not publish.

- User dropped JJ mode in layerctl, but the requested Deluge conversion remains in scope. Inspect the fork and convert its JJ-based history to the Git-centric layer format without requiring a JJ-mode projection.

## Current assignments

- /root/model: completed read-only history and filesystem analysis; owner verified the 34-commit linear stack and source pins.
- /root/projection: completed read-only walkthrough analysis; owner verified the documented edit and refresh flow with a local fixture.
- Owner: integrate findings, author walkthrough, convert and verify the fork, and maintain this plan.

## Conversion evidence and next steps

- The source stack has 34 linear commits above fork `main` (`9e3132dc17070695b40f69bada5565a33ce428b4`). All advertised branches point into that history. Preserve every commit boundary and original SHA, author, message, and JJ change-id as provenance. `711d48340ddb9c42d65db6088434b4b9c2ba5e58` has an empty tree change and message; use a documented marker message rather than inventing its original message.
- The base has case-colliding directories. This Mac uses a case-insensitive checkout; use a temporary case-sensitive filesystem for a faithful source reconstruction, and verify every layer tree against its original commit. The checkout is a blob-filtered partial clone; lazily fetch required objects through the authorized SSH remote.
- The skill walkthrough was exercised against an isolated local Git fixture, including add, refresh, check, graph, and projection deletion. It explains that conflict resolutions do not automatically update definitions.
