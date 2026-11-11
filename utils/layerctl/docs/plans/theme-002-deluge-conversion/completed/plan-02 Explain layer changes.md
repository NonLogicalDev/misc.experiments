# Explain Deluge layer changes

## Goal

Give each Deluge layer a detailed multiline commit message that explains what its operation introduces and why, grounded in the original patches and project notes. Preserve the original commit metadata in `provenance.json` and all firmware changes except the explicitly requested removal of `DEVIATIONS.md` and its obsolete firmware README link. Recalculate patch dependencies after extracting that document. Do not publish. [Owners](../../OWNERS.md).

## Work

- [x] Inspect each original change and draft a clear, evidence-based message; identify the no-op marker honestly.
- [x] Update the 34 manifests and extract `DEVIATIONS.md`, preserving unrelated fields and patch sections.
- [x] Validate wrapped messages and metadata; rebuild on a case-insensitive filesystem and compare original trees with the documented exceptions.
- [x] Checkpoint both checkouts locally and record the final recovery state.

## Assignments

- /root/model: completed message analysis and clone preparation metadata.
- /root/projection: completed message analysis and clone preparation plumbing.
- /root/integration_review: completed message analysis and independent review.
- Owner: handle the base layer, review and integrate all drafts, verify the composition, and update shared records.

## Current state

The clean `layerctl-conversion` worktree is at `e8c71d7b103e95a050e51c0c759308e512f27038`. The original messages are short subjects and remain recorded in `provenance.json`. Original changes and branch tips are preserved in the sibling source checkout. Review only the available evidence; a motivating claim must not go beyond what the patch establishes.

- User requested commit messages wrap at no more than 120 characters per line. Wrap the message text while preserving its paragraphs, TOML metadata, and file trees; verify the generated commits use the wrapped messages.

- User requested moving `DEVIATIONS.md` out of the composed firmware source. Preserve its latest contents at the definition repository root, remove its hunks from layer patches, update messages and dependency declarations from source evidence, and regenerate the graph. Compare every rebuilt tree to its original counterpart with `DEVIATIONS.md` removed; the final firmware README also omits the fork section that linked to the removed file. /root/projection and /root/integration_review: completed the extraction, graph and source-reference reviews.

- The final original patch adds a firmware README link to `DEVIATIONS.md`; omit that now-invalid README section as well. Preserve the original file byte-for-byte at the definition repository root, and explain its historical source-relative references. Dependency replay proves patch applicability, not firmware compilation or semantic independence.

- User requested moving the casing fix into clone preparation so normal case-insensitive filesystems work. Add a `git-clone` `pre-checkout-patch` applied to an isolated Git index after fetch and before materializing files. Keep the original imported commit as parent; use the existing casing patch as the base clone input and remove its separate layer. Validate transformed content, failure safety, refresh/recovery, and actual ordinary-filesystem replay. /root/model completed manifest, refresh and fingerprint handling; /root/projection completed clone preparation plumbing and focused tests. Owner integrates and verifies.

- Verified the original casing patch applies to a temporary Git index and produces the exact original casing-fix tree, without checking out case-colliding paths. Fold that patch into the base clone, preserving the original source parent and recording the absorbed layer in provenance. The converted stack then has 34 generated layers (base plus original layers 0003–0035).

- Verification: full layerctl Go suite passed in the isolated implementation copy; affected packages passed again in the actual checkout. `layerctl check` against the real SSH source passed with both workspace and `TMPDIR` on the case-insensitive filesystem. All 34 generated trees matched original firmware trees after excluding the relocated document and its removed README link; all generated messages matched their manifests and stayed within 120 characters. All dependency closures replayed in isolated indexes, and the formerly documentation-coupled Manual Slice layer rebuilt with only the base through the CLI. Source patch sections and relocated document were checked byte-for-byte, and the README graph matches the CLI. Firmware was not compiled.
- Independent check: the keybinding source-drift audit reports 38 changed source files in both the original checkout and reconstructed firmware. This pre-existing discrepancy was not changed by the migration. The original minilogue xd preset retains an uppercase KORG path reference that may not resolve on case-sensitive filesystems.

- Local checkpoints: layerctl `f4264d3725e599074b431a1dbb099d4a89ef2882` and Deluge definitions `417e6f9e4211ce6891e557e60285cfdbb5080418`. The original firmware checkout remains unchanged. The retained case-sensitive test image is unmounted; final verification used the ordinary filesystem. Neither checkpoint was pushed.
