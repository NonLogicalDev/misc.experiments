# Bounded seam fixture build

`build.py` prepares a fixture-only Vulkan executable from a clean layerctl projection with the ERP seam layer enabled and a completed compact baseline build. It recompiles all 32 feature variants of the nine affected projection and raster entry points, including the no-depth 3DGUT backward path, links the changed engine/raster objects ahead of the baseline archives, and records source, tool, fixture, and blob hashes. The generated registry intentionally omits the unrelated `fpbo`, `meshing`, and `pca_reg` shader families to stay within its 400 MiB scratch-tree cap. The Vulkan runtime reports a missing shader entry if the fixture reaches an omitted path. This executable is not a full trainer and must not be used to claim full-build correctness.

Run the script only with the pinned source/toolchain and an available 35 GiB reserve plus the 400 MiB scratch budget. It checks both during each child process and limits compilation to one process at a time. Example:

```sh
python3 validation/spirula-seam-build/build.py SEAM_LAYER_PROJECTION COMPACT_BASE_BUILD validation/spirula-erp-seam/seam.cpp NEW_OUTPUT_DIR --slangc PINNED_SLANGC --molten-root MOLTENVK_ROOT
```

The source projection must include disabled project layer `0006-erp-periodic-raster` enabled in an isolated layerctl definition; do not edit the existing generated projection. Run GPU fixtures only in a coordinated GPU window. A successful build is not a GPU, CUDA, AMD, or full-trainer result.

`build_trainer.py` is the separate full-registry trial path. It verifies and reuses the 32 fixture variants, compiles the remaining 50 affected variants from the same clean projection, checks the full 1,210-blob input inventory and the capability-filtered Mach-O registry byte-for-byte, then links the full existing trainer objects with the four modified engine/backend objects. No shader families are omitted. Its scratch cap is 600 MiB with the same 35 GiB reserve; the existing baseline binary is not replaced. It has not yet been exercised.
