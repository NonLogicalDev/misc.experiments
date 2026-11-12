# Modeling and topology

## Goal

Build file-first, code-driven B-rep modeling and reusable modules, with reliable geometry references and an inspectable adapter example.

## Current state

- Status: active. A draft couples topology reports to evaluated bodies and supports named graph instances. Full checks pass, but kernel import correspondence and exact downstream blend selection remain unproved; do not treat the draft as finished. The active plan records current investigation and assignments.
- [Modeling and adapter implementation](completed/plan-01%20Modeling%20modules%20and%20adapter.md) records the accepted API, checks, and limitations.
- [Persistent topology identity](active/plan-02%20Persistent%20topology%20identity.md) records the unfinished general identity work and next action.
- The adapter source is `examples/cooler_adapter.py`. It is a comparison prototype, not a verified manufacturing file.
- See the [checkout inventory](../_owner/state/worktrees.md) for local recovery limits.
