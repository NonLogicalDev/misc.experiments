# Experimental portable 360DVO backend

This is an experimental 360DVO inference port for full 2:1 equirectangular video. It computes correlation, spherical geometry, bundle adjustment and network operations with PyTorch tensors on Apple MPS or a PyTorch GPU backend. It does not create perspective views. It exports SphereDim JSON and CSV camera-to-world poses for the existing Blender importer. Monocular scale is arbitrary; some removed frames are reconstructed from relative motion, so the JSON `registered` count is an output count and does not mean every pose was independently observed.

## Layerctl source

`../../scripts/layerctl.sh` uses `go run` to execute the user's standalone `util.layerctl` at a pinned revision. It requires Go 1.26 or newer on PATH and the tool and its dependencies available in the Go module cache or downloadable. No layerctl checkout or executable is bundled.

## Apple Silicon setup

uv, Go 1.26 or newer, Git and tar must be installed; uv can locate or install Python 3.14. The pinned Python wheels target macOS ARM64. Go may need network access for module metadata even if the tool and dependencies are cached. From this directory:

```sh
../../scripts/fetch-runtime.sh gpu
./install-macos.sh
uv run --isolated --no-project --python 3.14 --with-requirements requirements-macos-arm64-py314.lock python work/portable_demo.py /absolute/path/input.mp4 /absolute/path/new-empty-output --weights ../../.artifacts/360dvo.pth --device mps --width 1024 --patches 96
```

The output folder must be absent or empty. Import `poses.json` with SphereDim's existing `src/blender_import.py`. The full input frame is resized to the requested width; `--stride` can sample fewer frames. The program requires a 2:1 video and a fixed camera calibration. The current model buffer and algorithm are experimental, and long footage, seam crossings, rolling shutter and changing exposure are not validated.

Run checks using `cd work` and `SPHEREDIM_DEVICE=mps uv run --isolated --no-project --python 3.14 --with-requirements ../requirements-macos-arm64-py314.lock python -m unittest discover -s tests -v`. uv keeps the runtime in its external cache; no environment is created inside the project.

## AMD and other systems

AMD GPU execution is designed to use a ROCm-enabled PyTorch build via PyTorch's `cuda` device API (`--device cuda`), not the original NVIDIA CUDA extensions. It has not been tested on AMD hardware. The pinned wheels are specifically macOS ARM64/Python 3.14 and cannot install on Linux; a compatible ROCm PyTorch and remaining Python dependencies must be supplied for that machine. The pinned `layerctl` command can run through Go on Linux. AMD offline dependency vendoring and hardware validation remain open.

## Evidence and limitations

On the 48-frame synthetic loop, the corrected port at 1024 pixels and 96 patches imported into Blender and yielded 0.153% trajectory RMS relative to traveled distance after similarity alignment. The worst-frame 95th-percentile image displacement was 1.669% after normalizing horizontal and vertical coordinates by their respective image dimensions, exceeding the 1% target. On the 40-frame `bridge_night` dataset clip, trajectory RMS was 0.369% relative to the reference path after alignment; that dataset reference is not independent ground truth for image alignment. Results are not a general accuracy guarantee. Seam handling retains limitations inherited from the original kernels. Training, GPU performance at scale, other GPU hardware, and every target scene remain unverified.

The upstream source revision is pinned in the layer definition and fetched by `layerctl`; see `LAYERCTL.md`. The model is the upstream [published checkpoint](https://drive.google.com/file/d/17x0V5DnXye5f1qlWLK80yRG6luInPmid/view?usp=sharing). `requirements-macos-arm64-py314.lock` and `scripts/fetch-runtime.sh` record the wheel and checkpoint hashes. Each Python wheel includes its own distribution metadata and licenses. Preserve the upstream license and review model and dataset terms before redistribution.

Detailed multi-scene results and exported poses are in [validation/portable-360dvo](../../validation/portable-360dvo/README.md). The moving-object scene also misses the image target, with a 1.270% worst-frame p95.

The deliberately low-texture scene produced 24 poses but failed badly: 3.332% trajectory RMS and 32.791% worst-frame image p95. A complete pose count is not a reliability score.

## Layer contents

Documentation stays here because layerctl permits only manifest-referenced inputs inside each layer directory.

### 360DVO upstream

Fetches [chris1004336379/360DVO](https://github.com/chris1004336379/360DVO) at `46f5ed0735d39aff29a75f28c360600340879b35`. This layer adds the unmodified upstream source. The revision and clone settings are in [layer.toml](layers/0001-upstream/layer.toml). Composition and setup commands are in [the integration README](README.md).

### Portable GPU inference patch

Applies [portable-gpu.patch](layers/0002-port/portable-gpu.patch) after the pinned upstream layer. The patch replaces CUDA-specific inference operations with PyTorch tensor operations for native equirectangular input and adds pose export and regression checks. Apple MPS has been exercised; AMD execution still requires hardware validation. Read [the integration README](README.md) for setup, test commands, and measured accuracy. Edit this patch layer rather than the generated source in `vendor/360DVO/work`.
