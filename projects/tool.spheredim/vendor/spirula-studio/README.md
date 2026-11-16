# Spirula Studio renderer source

The upstream layer pins [Spirula Studio](https://github.com/harry7557558/spirula-studio) release commit `667e353bca3941303a4d93e93aa8ae3f2c202712`. The layerctl projection in `work/` is generated source; keep authored upstream changes in separate patch layers. The local projection's synthetic commit is not the upstream commit. No renderer patch has been applied or GPU regression passed yet.

From this directory, initialize the definition as a Git repository if necessary, then run the project’s external layerctl wrapper with Go available on PATH:

```sh
../../scripts/layerctl.sh graph
../../scripts/layerctl.sh projection create source --worktree "$PWD/work"
../../scripts/layerctl.sh check
```

The source projection was checked with layerctl and occupies approximately 62 MiB. The exact-release calibration warp and raster seam findings and required regressions are described in [the renderer audit](../../docs/research/spirula-native-erp-audit.md). The current calibration-warp interface does not distinguish equirectangular from pinhole cameras; changing its boundary behavior requires explicit camera-mode plumbing and tests for both paths.

A Vulkan test configuration with GUI, SfM and SAM disabled succeeded on Apple arm64 using CMake 4.4.3, Slang 2026.12.1 and MoltenVK 1.4.2. CMake reported 1,210 shader blobs even when selecting an individual parity test. No build or GPU test has been run. The verified release archives were:

- `slang-2026.12.1-macos-aarch64.tar.gz`: SHA-256 `18461d1f772b68d962c5a3508f1aa7e22b0a740da0b6c7ac948833d86641d870`.
- `MoltenVK-macos.tar`: SHA-256 `f95765a6229cb7b915990a2890ce12ebe36a730b021545d3d52ae69ce4c4024e`.

Keep acquired archives, unpacked toolchains, builds, model outputs and recording data outside Git. Measure available memory, disk and concurrent GPU activity before building or running tests. A source-level or CPU reproduction is not a GPU proof.

## Experimental SfM rotation-prior layer

The `0002-rotation-priors` layer adds `--rotation-priors FILE` to `spirula-sfm auto`, using CSV columns `image,qw,qx,qy,qz,sigma_degrees`. Each quaternion is camera-to-world in one common frame and each image name is relative to the image directory. The layer checks exact image coverage, unit quaternions, positive uncertainty and duplicate names. It places one representative per declared rigid frame into a temporal chain, gives the global rotation initializer separate prior edges even when visual edges exist, and adds soft relative-rotation factors to BA. It rejects combining these priors with video telemetry. The global initializer gives each prior edge the graph's ordinary unit weight; the supplied sigma is used by BA, not as an initializer weight. Adjacent relative factors share an absolute orientation sample, so their errors are correlated even though the current BA treats them as independent. The sigma is not a calibrated joint likelihood.

The layer also retains a fixed, nonzero rig baseline when the sensor or ordinary upright gauge proposes rescaling, preserving the transformed camera centroid and reporting the discarded scale. Other metric-reference gauge paths have not been qualified. The layer is experimental and is not a renderer seam fix. CSV source-frame alignment and camera basis remain the caller's responsibility.

A standalone Apple Vulkan build configured with the SHA-256-verified Slang and MoltenVK archives listed above; the unpacked toolchains were placed outside Git at `/private/tmp/spheredim-spirula-deps`. The build directory below is also outside Git. The pinned source's standalone target requires the layer's Vulkan compile definition.

```sh
cmake -S work -B /private/tmp/spheredim-spirula-sfm-build -G 'Unix Makefiles' \
  -DSS_BACKEND=vulkan -DSS_BUILD_GUI=OFF -DSS_BUILD_SFM=ON -DSS_BUILD_SAM=OFF \
  -DSS_NN_METAL=OFF -DSS_ENABLE_PATENTED=OFF -DSS_SEPARATE_TOOLS=ON \
  -DSS_SFM_REALS=float -DSS_SFM_LOSSES=huber \
  -DSS_SLANGC=/private/tmp/spheredim-spirula-deps/slang/bin/slangc \
  -DSS_MOLTENVK_DIR=/private/tmp/spheredim-spirula-deps/molten/MoltenVK \
  -DCMAKE_DISABLE_FIND_PACKAGE_OpenMP=ON
cmake --build /private/tmp/spheredim-spirula-sfm-build --target spirula-sfm --parallel 1
```

Run the small CPU convention/input test directly from `work/` with `/usr/bin/c++ -std=c++17 -Isrc src/sfm/tests/sfm_rotation_csv_test.cpp -o /private/tmp/sfm-rotation-csv-test && /private/tmp/sfm-rotation-csv-test`. The standalone binary uses `spirula-sfm auto ...`, not `spirula-sfm sfm auto ...`. The CPU test checks quaternion direction, sigma, duplicate and malformed input, and one factor for a paired rig frame. GPU reconstruction and fixed-baseline gauge behavior require the real-run checks; do not infer them from the CPU test.

The revised standalone target built successfully on 2026-11-15 in the external build directory, using 66 MiB. Its SHA-256 was `7c088ed62ea6687a2b55e436ec15a1db97ef0b33e6822ccecb5be1b00fabca0c`; `--version` reports layerctl's synthetic source revision and a dirty suffix, not the upstream release identifier. The layer passed `layerctl check`, and the direct CPU test passed. The binary and its `auto --help` started successfully. No GPU SfM result or renderer fix is established by these checks. `--rotation-priors` is listed by `auto --help`. The prior is used by initialization and BA, without applying the telemetry source’s hard seed or registration gates.

## Final rig refinement and measured execution

Layer `0003-final-prior-refinement` includes late registered frames in the final joint solve for explicit CSV priors. It verifies all registered images, rig body variables, prior factors and fixed extrinsics before solving. This is an SfM change; the renderer seam fix remains open. The final standalone binary SHA-256 is `e4005229cb294e3860c62968e87a9818044c1a70e89f4401677a0b76234f8196`. All three layers passed layerctl checks; the CPU CSV/convention and final-layout checks passed. Native Apple GPU runs exercised 16 and 138 body frames. See [measured rig results](../../docs/research/rig-sfm-comparison.md) for coverage, actual errors and CPU/GPU comparison. Earlier configuration/build observations above are historical; they do not describe the final SfM validation state. No renderer GPU seam regression or AMD execution is claimed.
