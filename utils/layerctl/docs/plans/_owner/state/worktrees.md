# Worktree inventory

- Repository: https://github.com/NonLogicalDev/misc.experiments
- Checkout: `/Users/nonlogical/Projects/remote/github.com/NonLogicalDev/misc.experiments`; utility `utils/layerctl`; manual clone on this Mac; branch `main`.
- Initial HEAD/base: `5de5308d7f566595efe80a45fd82e76959ff36ea`; pushed to remote main, verified in the preceding turn. Local `origin/main` is stale because that push used an explicit SSH URL.
- Git common directory: checkout `.git`. Its storage survives ordinary process termination; host replacement durability is unverified. Remote contains the initial commit; new local work requires a checkpoint.
- Sparse checkout: none. Reconstruct with `git clone git@github.com:NonLogicalDev/misc.experiments.git` and check out the recorded checkpoint.
- Scope and authorization: [owners](../../OWNERS.md); [active plan](../../theme-001-layer-format/completed/plan-01%20Manifest%20operations.md).

- Latest task checkpoint: `e001b8a9438826f207afeb22cc0399c5df44e453` on local `main` (2026-11-11); contains the initial manifest/migration draft, not complete ordered recovery. Local object storage is on this Mac; survival of host replacement is unverified. Additional uncheckpointed implementation is in `/private/tmp/layerctl-manifest-work`, which is temporary.

- Verified implementation checkpoint: `a65ce88fad31098d7d4349da4613ef0fe2e7d820` on local `main`, 2026-11-11. Full tests and CLI smoke passed. Local Git storage is on this Mac; survival after host replacement is unverified. This implementation is not pushed.

- Current verified checkout (2026-11-11): HEAD `35f0928713e7e5cd3ec5a53ba0fb3fdb49a370dd`, origin/main and merge base `efaeddf8595378c181d1ea98c06426228f1ce7bf`, ahead 6, behind 0, non-sparse. Source checkout is clean aside from this task's owner-plan changes. Active work: [repository composition](../../theme-001-layer-format/active/plan-02%20Repository%20composition.md).

- Deluge source checkout: `/Users/nonlogical/Projects/remote/github.com/NonLogicalDev/fork.DelugeFirmware`, Git common directory `.git`; clean branch `nl/latest`, HEAD and origin/nl/latest `2391b7cad4907843890d8b6c052651a77abd6bbf`, merge base with origin/main `9e3132dc17070695b40f69bada5565a33ce428b4`. Manual SSH partial clone, non-sparse, on this Mac; host replacement durability unverified. Reconstruct with `git clone --filter=blob:none git@github.com:NonLogicalDev/fork.DelugeFirmware.git`; the original branches remain on the remote. See the [conversion plan](../../theme-002-deluge-conversion/completed/plan-01%20Convert%20JJ%20layers.md).
- layerctl implementation checkpoint `334770a513e65ebbe9c0cc63d2d1e72a842fa547`, local main, 2026-11-11; ahead of `origin/main` by 9, behind 0. The checkpoint is not published.

- Deluge conversion checkpoint: local branch `layerctl-conversion` at `5967d2e3e82e60a9739ffed2a9b34ec1c50bca8e`, an independent definition-history root held in the fork checkout Git object database. The branch is not pushed; ordinary process termination preserves it but host replacement durability is unverified. Original `nl/latest` remains checked out and clean. Temporary validation used the case-sensitive image `/private/tmp/layerctl-deluge-case-sensitive.sparseimage`; the local branch is the durable working copy on this Mac.

- Deluge definition worktree: `/Users/nonlogical/Projects/remote/github.com/NonLogicalDev/fork.DelugeFirmware-layerctl`, branch `layerctl-conversion`, HEAD `5967d2e3e82e60a9739ffed2a9b34ec1c50bca8e`, no upstream, no sparse checkout. It shares `/Users/nonlogical/Projects/remote/github.com/NonLogicalDev/fork.DelugeFirmware/.git` with the original checkout; no remote contains this branch. Reconstruct locally with `git -C /Users/nonlogical/Projects/remote/github.com/NonLogicalDev/fork.DelugeFirmware worktree add /Users/nonlogical/Projects/remote/github.com/NonLogicalDev/fork.DelugeFirmware-layerctl layerctl-conversion`. The temporary case-sensitive image was unmounted and retained at `/private/tmp/layerctl-deluge-case-sensitive.sparseimage`; temporary storage may be removed by the system.

- Latest Deluge definition worktree checkpoint: `7f7c7bdfd83dfc537972268a888b43c46d297053` on local `layerctl-conversion`, containing the generated README graph; no remote upstream. Storage and recovery limitations remain as described above.

- Latest local checkpoints: layerctl `7e06e241a550f835808816eae2e9e05dfdb963de` on misc.experiments `main`; Deluge definitions `e8c71d7b103e95a050e51c0c759308e512f27038` on `layerctl-conversion`. Neither checkpoint has been pushed; checkout storage and recovery limitations remain as described above.
