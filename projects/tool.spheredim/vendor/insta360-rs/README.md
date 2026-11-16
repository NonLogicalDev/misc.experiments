# insta360-rs observation layer

This separate experimental layer imports [insta360-rs](https://github.com/OpenSpeleo/insta360-rs) at `b4f3845feb105b70c1928ed4316fe1d8a963bc36` and applies a task-owned observation patch. The source is the audited 0.2.1 checkout; it has not been proven to match the historical export's wheel. The default exporter mode remains the upstream stitch. Observation modes are experimental and require the fixed seam, GPU backend, FlowState stabilization and rolling-shutter correction off for this sample. The composed source checkout lives in `work/`. Build outputs, Python environments, recordings and generated frames stay outside the project.

From this directory, after initializing this definition directory as a Git repository, the external helper can compose a fresh source tree:

```sh
../../scripts/layerctl.sh graph
../../scripts/layerctl.sh projection create observation --worktree "$PWD/work"
../../scripts/layerctl.sh projection list
../../scripts/layerctl.sh check
```

The tested local composition used a Git URL rewrite to a local shallow mirror of the exact upstream commit. A fresh composition from GitHub requires network access. The tested Apple arm64 build used FFmpeg 9.0.2 development libraries, Rust 1.97.0, two jobs, incremental compilation disabled and an isolated target directory. From `work/`, with `PKG_CONFIG_PATH` pointing to FFmpeg's pkgconfig directory and a build target outside the project:

```sh
cd work
RUSTUP_TOOLCHAIN=1.97.0 CARGO_TARGET_DIR=/absolute/path/outside/project/target CARGO_BUILD_JOBS=2 CARGO_INCREMENTAL=0 CARGO_PROFILE_RELEASE_DEBUG=0 cargo rustc --release -p insta360-rs-python --features extension-module -- -C link-arg=-undefined -C link-arg=dynamic_lookup
```

The current local `work/` projection was moved intact from its original composition and is registered with layerctl. Its compiled extension remains in the external build directory; moving source does not rebuild it. Use uv-managed Python environments outside the project, for example `uv run --isolated --no-project --python 3.12 --with numpy --with pillow ...`, and set `UV_CACHE_DIR` to an external cache. See the audit for how to expose a compiled extension to the sample runner. Monitor target, package caches and free space during builds. The release build required macOS dynamic-lookup flags for the Python extension. The inspected upstream pins Rust 1.97.1; this local build used installed 1.97.0, so its equivalence to the wheel is unverified. The package resources and upstream NOTICE have separate terms; review them before redistribution.

The patch emits color, binary validity or lens ownership in separate passes from the same projection and stabilization. It avoids blend, gain and optical-flow correction in observation mode, and cuts a narrow weight-crossover region. This cut is a proposed uncertainty margin, not measured disagreement or a claim of absent physical coverage. Full per-pixel source coordinates and ray origins are not yet emitted. The mask is a conservative predicted support check, not proof of physical visibility. Validate outputs and exact timestamps before treating the result as reconstruction evidence. See [the audit](../../docs/research/insta360-source-observation-audit.md).

## Layer contents

Documentation stays here because layerctl permits only manifest-referenced inputs inside each layer directory.

### Upstream source layer

Imports [insta360-rs](https://github.com/OpenSpeleo/insta360-rs) commit `b4f3845feb105b70c1928ed4316fe1d8a963bc36` with shallow depth one. This audited source identifies itself as 0.2.1; correspondence with the historical installed wheel and its build features is unverified. See the [integration README](README.md) for composition and build commands. Do not edit a generated source projection as the durable patch.

### Experimental observation patch

This layer applies `observation.patch` to the pinned upstream source. Unset `SPHEREDIM_OBSERVATION_MODE` retains the upstream output; `color`, `validity` and `ownership` request separate observation passes. Invalid values fail. Observation mode chooses one projected source, bypasses inter-lens blending, gain and correction flow, and marks unsupported or crossover pixels black. The crossover range is a provisional weight-based margin, not measured disagreement. Validity and red/green ownership require the same frame selection and transforms across passes. The helper runner checks those outputs and preserves PNG frames as canonical samples; MP4 is a preview.

The mask checks conservative source bounds and a neighborhood of calibration mask values. This does not establish physical sensor synchronization, exact lens origins, scene correspondence or metric calibration. Source coordinates and per-frame stabilization transforms are not yet exported. The patch must be tested for the selected GPU, recording and sample before relying on its output. See the [integration README](README.md) for composition and build commands.

The current patch also supports `lens0`, `lens1`, `mask0` and `mask1` diagnostic modes for independent full-sphere observations. `SPHEREDIM_LENS1_INVERSE_QUAT_WXYZ` accepts one normalized inverse rotation in `w,x,y,z` order. It is applied to the camera ray before lens 1's embedded orientation in observation modes; unset means identity. An invalid value fails. The original upstream output remains unchanged when observation mode is unset. Use a recording-specific fit only after checking held-out frames, and retain the fit report and input hashes. See the [source audit](../../docs/research/insta360-source-observation-audit.md) for the local experiment and remaining residuals.

### Experimental camera-relative readout layer

`0003-camera-relative-readout` is disabled. It proposes allowing the explicit `stabilization=OFF`, `rolling_shutter=REQUIRED` combination to prepare source-row poses while retaining the reference camera frame. `OFF` with `AUTO` retains the existing no-correction behavior. The patch includes motion-table tests, analytic CPU source coordinates, independently forward-generated sphere images, and CPU/GPU coordinate-texture and image comparisons for stationary, synchronized and unequal-lens timing. The tests have not been compiled or run. Before using it on the recording, execute these checks and independently validate timestamp and readout assumptions. The layer does not establish the recording's physical readout direction or prove that rolling shutter caused the reconstruction blur.
