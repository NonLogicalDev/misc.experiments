# Project map

Read this map first, then [owner guidance](AGENTS.md), [owners](OWNERS.md), and the relevant execution state.

- [Project overview](../../README.md): file-first, agent-first code-driven CAD; Python is the first modeling language.
- Rust core and CLI: `../../src/solidrecipe-core/` and `../../src/solidrecipe-cli/`; Python authoring API: `../../src/solidrecipe-core/python/`; React Three Fiber viewer: `../../src/solidrecipe-viewer/`.
- [Modeling and topology](theme-002-modeling/EXEC_STATE.md): modules, adapter prototype, geometric operations and unfinished general identity propagation.
- [General topology queries and face-attached profiles](theme-002-modeling/active/plan-03%20General%20topology%20queries%20and%20face-attached%20profiles.md): current design investigation of general queries, subdivision, sketches and constraints.
- [Viewer](theme-001-viewer/EXEC_STATE.md): in-process preview, parameters, presets and interaction.
- [Architecture](../../docs/architecture.md) and [feature tracking](../../docs/feature-tracking.md): authoritative technical details and explicit topology limits.
- [Planning maintenance](theme-000-meta/EXEC_STATE.md) and [checkout inventory](_owner/state/worktrees.md): owner records and local recovery boundaries.

Last audited: 2026-11-11. Evidence: source, project documentation, Git status, the adapter and viewer checks. Re-audit after an architecture or ownership change, before a handoff, or after 30 minutes of sustained work. Runtime viewer state, physical adapter fit and any external backup remain unverified until checked again.
