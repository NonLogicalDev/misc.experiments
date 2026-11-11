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
