# Checkout inventory

- Project: solidrecipe; source and checkout: `/Users/nonlogical/Projects/local/active/tool.solidrecipe` on the local host.
- [Owners](../../OWNERS.md); [viewer work](../../theme-001-viewer/EXEC_STATE.md).
- Git common directory: `/Users/nonlogical/Projects/local/active/tool.solidrecipe/.git`; branch: `master`.
- No remote or upstream is configured. Local repository history and the SolidCore submodule are on this machine; survival across machine replacement has not been verified.
- Last checkpoint verified before the final validation: `b969da1c51d3a584b4ac17a8dc9594fb5c408de8`; consult `git rev-parse HEAD` and `git status` for current state.
- There is no remote base or merge base. This is the original checkout, not a linked worktree. The SolidCore dependency is recorded as `vendor/solidcore`; initialize it with `git submodule update --init --recursive` after recovering the repository.
- Recovery requires a backup of this local repository and its Git object database; a path or hash alone cannot reconstruct it on another machine. No remote backup has been verified.
