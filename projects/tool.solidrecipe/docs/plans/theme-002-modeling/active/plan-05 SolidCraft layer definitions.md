# SolidCraft layer definitions

Status: active. [Owners](../../OWNERS.md).

Move all SolidCraft patches into checked-in layerctl definitions under `vendor/solidcraft`, following the SphereDim vendor layout. The layer manifests and their patch files are the authoritative inputs. The user directed removal of the redundant upstream submodule: fetch the pinned commit directly via layerctl, preserve the existing composed workspace, and do not touch unrelated work in the parent repository. The historical untested edge-split draft is a disabled layer, not an applied dependency patch.

Validate clean composition and existing-workspace migration, byte-for-byte equivalence to the current dependency, repeat preparation, and refusal to overwrite changed work. Reuse existing Rust build artifacts and remove temporary test files.

The user also requested a clearer project root: keep orchestration and project documentation there, put Rust workspace files in `src`, and Python packaging files beside `src/solidrecipe-core/python`. Keep generated previews and build state under `.work`; update commands, tests and active documentation. Preserve existing generated files when moving them.

2026-11-15: The five active patches and disabled draft are now layer files. Layerctl replay succeeded offline against the clean upstream checkout, and the new composed tree exactly matches the earlier prepared tree. Repeat preparation and modified-workspace and modified-upstream refusal passed. The former generated layerctl directory was removed after verification; the old preview artifacts were preserved under `.work/artifacts`. Offline `cargo check --workspace`, workspace metadata, package formatting, Python import and three graph-level tests passed. The check used no incremental compilation or debug info, and its temporary target was removed. Viewer type checking and formatting passed via installed tools, but `make format-check` could not finish through pnpm because its original temporary store is missing and registry access failed. Full runtime tests remain unverified after the move because the former debug executable was absent.

2026-11-15: At the user's direction, removed the redundant upstream SolidCraft submodule. The manifest now supplies the URL directly to layerctl, so first composition requires network access. Existing preparation still works without fetching. A fresh isolated composition using the existing projection as a local Git substitute reproduced the same tree; direct network fetching was not tested.
