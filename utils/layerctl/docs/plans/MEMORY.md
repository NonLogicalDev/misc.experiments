# Project map

Read [owner instructions](AGENTS.md) and [ownership](OWNERS.md) before owner work. [README](README.md) links the work. The layer manifest, capture, replay, and migration work and its verified implementation are tracked in [execution state](theme-001-layer-format/EXEC_STATE.md). The implementation is in `../../internal/`; existing upstream behavior is described in `../../UPSTREAM_GUIDE.md`. [Worktree inventory](_owner/state/worktrees.md) records recovery information. [Task zero](theme-000-meta/EXEC_STATE.md) maintains this plan home.

Last audited: 2026-11-11. Evidence: user direction, current checkout and upstream guide. Audited after implementation against the plan, source, and validation; audit on the next material change.

2026-11-11: User redirected the layer-format work toward multiple repositories and `git-clone` base operations. See the active plan; prior Codex-specific upstream model is being reassessed.

DelugeFirmware conversion is complete locally; see [its plan](../../../../../fork.DelugeFirmware-layerctl/docs/plans/theme-002-deluge-conversion/EXEC_STATE.md). The fork retains its original refs, and local branch `layerctl-conversion` holds the verified definitions in the linked `fork.DelugeFirmware-layerctl` worktree.

The layerctl authoring and management walkthrough is in `../../skills/layerctl/references/authoring.md`; checkpoint `ff16948` includes it. Deluge clone preparation now runs a case-normalization script against a Git index before checkout; the full rebuild passed on a case-insensitive workspace and temporary directory.

2026-11-11: Generated commit messages now use multiline TOML while retaining exact bytes. Graphs show explicit dependencies or the preceding enabled layer when omitted; `depends-on = []` declares none. Deluge manifests declare dependencies validated by isolated patch replay; see the [conversion plan](../../../../../fork.DelugeFirmware-layerctl/docs/plans/theme-002-deluge-conversion/completed/plan-01%20Convert%20JJ%20layers.md).

Deluge follow-up is complete: messages explain each layer and wrap at 120 characters, while `DEVIATIONS.md` is maintained at the definition root; see [execution state](../../../../../fork.DelugeFirmware-layerctl/docs/plans/theme-002-deluge-conversion/EXEC_STATE.md).

Completed layerctl follow-up: bare Git pre-checkout scripts return a commit or tree SHA, and clone `dir` can be omitted; see [plan](theme-001-layer-format/completed/plan-03%20Pre-checkout%20script.md).

Completed Deluge follow-up: use the upstream SynthstromAudible repository as the base; see [plan](../../../../../fork.DelugeFirmware-layerctl/docs/plans/theme-002-deluge-conversion/completed/plan-03%20Use%20upstream%20source.md).
