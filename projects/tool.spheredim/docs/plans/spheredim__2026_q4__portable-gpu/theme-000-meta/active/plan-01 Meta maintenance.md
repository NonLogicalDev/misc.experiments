# Meta maintenance

Maintain the plan root, owner register, project map, and recovery records. [Owners](../../OWNERS.md). This is the standing task zero and remains active while the owner is active.

- 2026-11-14: Initialized under the user's requested `docs/plans` location. Verify links and the current state before handoff.

- 2026-11-15: Reused the existing tracking/reconstruction domain for the Terra quality roadmap; linked plan 04 from the README and project map. Preserve plans 01–03 and existing ownership. Checked plan 04 local links and recorded source-only versus runtime evidence.

- 2026-11-15: User requests upstream directory names, READMEs for integrations/layers, and one shared layerctl helper in scripts. Rename vendor/360dvo-port to vendor/360DVO, retain authored port layer and local composition/environment, move helper to scripts/layerctl.sh, and repair current references and local prefix metadata. Move generated vendor/runtime FFmpeg install to ignored .artifacts/ffmpeg-runtime and update build/discovery paths; remove only empty leftover wheel directories. Existing upstream submodule READMEs remain unmodified. Exporter worker owns vendor/insta360-rs layer/docs, owner owns these packaging changes.

- 2026-11-15: Corrected the owner's mistaken project-level work directory. User specifies `vendor/<name>/{layers,work}`. `vendor/360DVO` holds definition/docs/lock and ignored work; vendor/360DVO/work/{source,env} holds composed source and environment; .artifacts/ffmpeg-runtime holds the generated FFmpeg install. Preserve active files and repair entry points in place without rebuilding dependencies.

- Moved source/environment back to `vendor/360DVO/work/{source,env}`, repaired environment prefixes and layerctl workspace record, and removed the empty project `.work` directory. `/vendor/*/work/` is ignored.

- 2026-11-15: Final clarification: `vendor/<name>/work` is the composed source checkout itself. Flattened 360DVO `work/source` into `work`; removed both superseded local Python environments after external uv runtime import checks. Setup and usage now use `uv run --isolated --no-project --with-requirements` with pinned dependency files; environments stay in the external uv cache. Exporter worker applies the same source layout to insta360-rs.

- Both vendor source checkouts now live directly at `vendor/{360DVO,insta360-rs}/work`. layerctl check/list passed for both; CPU/GPU external uv imports and CLI help passed. No source duplication or rebuild. Viewer HTTP 200 after migration.

- 2026-11-16: Refresh the project map and current execution after the native 2048 and 450k trials, direct LAN/mobile delivery, and reframed report. Preserve historical entries; replace stale current-state claims using measured comparisons and verified Git HEAD. Private report derivatives remain local.

- 2026-11-16: Carry forward the operator correction that completed candidate reconstructions must be inspectable in the live state-driven viewer even when their metrics regress. Availability for inspection is separate from which model is the measured incumbent. Viewer worker publishes existing artifacts without copying large files.
