# Project map

Read [owner instructions](AGENTS.md) and [ownership](OWNERS.md) before owner work. [README](README.md) links the work. The layer manifest, capture, replay, and migration work and its verified implementation are tracked in [execution state](theme-001-layer-format/EXEC_STATE.md). The implementation is in `../../internal/`; existing upstream behavior is described in `../../UPSTREAM_GUIDE.md`. [Worktree inventory](_owner/state/worktrees.md) records recovery information. [Task zero](theme-000-meta/EXEC_STATE.md) maintains this plan home.

Last audited: 2026-11-11. Evidence: user direction, current checkout and upstream guide. Audited after implementation against the plan, source, and validation; audit on the next material change.

2026-11-11: User redirected the layer-format work toward multiple repositories and `git-clone` base operations. See the active plan; prior Codex-specific upstream model is being reassessed.

DelugeFirmware conversion is complete locally; see [its plan](theme-002-deluge-conversion/EXEC_STATE.md). The fork retains its original refs, and local branch `layerctl-conversion` holds the verified definitions.

The layerctl authoring and management walkthrough is in `../../skills/layerctl/references/authoring.md`; checkpoint `ff16948` includes it. Deluge reconstruction requires a case-sensitive workspace and temporary directory; see its plan for the tree-by-tree verification.
