# Convert DelugeFirmware from JJ

## Goal

After layerctl is implemented and verified, carefully convert `https://github.com/NonLogicalDev/fork.DelugeFirmware` from its JJ-based approach to the new layerctl format. Preserve source data and provenance. Do not publish unless asked. [Owners](../../OWNERS.md).

## Completion criteria

- [ ] Resolve the existing checkout or clone the requested repository at its configured project path; read applicable instructions and inspect its JJ/Git state.
- [ ] Identify its base repositories, revisions, JJ stack, changes, and intended outputs without discarding work.
- [ ] Capture an equivalent layerctl definition with traceable source and validate a clean reconstruction against the accepted JJ state.
- [ ] Document evidence and limitations, checkpoint locally, and preserve rollback material.

## Current state

Pending: finish and verify the layerctl re-architecture first. The expected checkout path did not exist on initial inspection.

- User dropped JJ mode in layerctl, but the requested Deluge conversion remains in scope. Inspect the fork and convert its JJ-based history to the Git-centric layer format without requiring a JJ-mode projection.
