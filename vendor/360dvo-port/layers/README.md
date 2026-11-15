# SphereDim 360DVO layer

This repository contains the `layerctl` definition for the experimental SphereDim 360DVO GPU port. The first layer imports upstream commit `46f5ed0735d39aff29a75f28c360600340879b35`; the second applies `portable-gpu.patch`. The vendored archive contains a shallow bare Git repository of the upstream source, including its license. `layerctl-offline.sh` redirects the upstream URL to that archive for each invocation and requires Git, tar and `layerctl`.

From this directory, set `LAYERCTL_BIN` to the executable if it is not on PATH:

```sh
./layerctl-offline.sh check
./layerctl-offline.sh projection create portable --worktree /absolute/path/to/new-worktree
```

The target must not exist. Preserve this Git repository and the layers when updating a projection. Runtime wheels and model weights are supplied separately by SphereDim. The patch provides inference only. It replaces the CUDA extensions with PyTorch tensor operations and uses full equirectangular frames; it does not create perspective views. The inherited optimizer and correlation retain upstream's treatment of the equirectangular seam, which is not yet validated for seam-crossing features.
