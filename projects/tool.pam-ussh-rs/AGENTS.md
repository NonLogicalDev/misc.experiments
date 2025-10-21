# Repository Guidelines
The `pam-ussh-rs` crate implements a PAM module mirroring the behavior of the legacy Go variant while targeting a secure Rust codebase.

## Project Structure & Module Organization
- `src/` holds the Rust crate; place module entry points in `lib.rs` and keep PAM helpers under `src/pam/`.
- `tests/` contains integration suites that exercise full PAM flows; use fixture data under `tests/data/` when adding regression cases.
- `backup/pam-ussh-go/` is read-only reference material from the original Go module; consult it to confirm feature parity but do not modify it.
- Packaging assets (e.g., Debian recipes) will live under `dist/` once we mirror the Go packaging layout.

## Build, Test, and Development Commands
- `cargo build` compiles the module against the default target.
- `cargo test` runs unit and integration tests; append `-- --nocapture` to view stdout.
- `cargo fmt` applies `rustfmt` to all sources; run before committing.
- `cargo clippy --all-targets --all-features -D warnings` enforces lint gates.
- `just save` stages all changes and records a timestamped commit (`<date> :: save`) for quick snapshots.

## Coding Style & Naming Conventions
Use 4-space indentation and keep modules/functions snake_case. Types, traits, and enums stay in PascalCase, and constants in SCREAMING_SNAKE_CASE. Document any `unsafe` blocks with a one-line safety comment. Prefer explicit error enums over `anyhow` to mirror the Go error surface unless localized spikes demand otherwise.

## Testing Guidelines
Co-locate fast unit tests beside their modules with `#[cfg(test)]` and name functions `modname_behaviour`. Place end-to-end PAM flows in `tests/`. When borrowing cases from `backup/pam-ussh-go/pam_ussh_test.go`, keep filenames aligned to simplify diffs. Target comparable coverage to the Go suite; add regression tests for every bugfix.

## Commit & Pull Request Guidelines
Commits should be task-focused; follow the project pattern `YYYY-MM-DD HH:MM TZ :: summary` or `area: summary` for clarity. Reference issue IDs in the title when applicable. PRs must describe the change, list validation commands run, and note any configuration steps (e.g., updates to `/etc/pam.d`). If behavior diverges from the Go reference, call it out explicitly.

## Security & Configuration Tips
Handle secrets via PAM handles only; never write SSH keys or passphrases to logs. Keep sample configs under `examples/pam.d/` and document default values inside README updates to avoid misconfigurations on deploy.
