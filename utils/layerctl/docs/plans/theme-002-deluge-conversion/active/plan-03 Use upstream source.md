# Use the upstream Deluge repository as the base

## Goal

Use `https://github.com/SynthstromAudible/DelugeFirmware` as the base `git-clone` source for the converted Deluge layers. Preserve the fork's changes and provenance, and keep local work unpublished. [Owners](../../OWNERS.md).

## Work

- [ ] Check the upstream refs and whether they contain the currently pinned base commit.
- [ ] Change the base source and adjust layer definitions only as needed to preserve the intended firmware.
- [ ] Verify source ancestry, reconstructed firmware, README, and provenance; checkpoint locally.

## Current state

The clean definition worktree is on `layerctl-conversion`; its base currently fetches the fork at `9e3132dc17070695b40f69bada5565a33ce428b4` from `nl/latest`. The requested upstream default branch is `main`, with a `community` branch also present. Determine actual ancestry before selecting a ref or revision.

- User requested all Deluge plans in the Deluge definition repository under `docs/plans`. Move the existing conversion theme and its history there, preserving the owner identity and worktree recovery records; repair links and verify both plan roots before continuing.
- Verified the original pinned base commit is reachable from upstream `main`; it is not reachable from upstream `community`. Use the upstream SSH URL and `refs/heads/main`, retaining the pinned commit.
