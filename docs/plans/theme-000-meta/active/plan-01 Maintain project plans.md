# Maintain project plans

## Purpose

Keep the Tasker_Stream project map, owner register, and plans in `docs/plans`.

## State

Active. The user requested this location on 2026-11-10. The project has an initialized Git repository with no commits; existing files are uncommitted. No checkpoint has been created because the user requested Git initialization, not a commit.
- 2026-11-10: User requested correction of the latest commit to remove the accidentally tracked Python bytecode and fix recursive ignore rules. Preserve unrelated working changes.
- 2026-11-10: User requested consistent Rust and TypeScript/TSX formatters. Use rustfmt and a pinned Prettier dependency with repeatable check and write commands.
- 2026-11-10: Chose Biome rather than Prettier after the user requested the best practical option. Use Biome for TypeScript, Ruff for Python, and rustfmt plus Clippy for Rust; checks must fail on lint or formatting violations.
