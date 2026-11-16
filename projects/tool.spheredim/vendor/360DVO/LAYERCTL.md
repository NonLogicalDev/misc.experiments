# SphereDim 360DVO layer

The first layer imports [360DVO](https://github.com/chris1004336379/360DVO) commit `46f5ed0735d39aff29a75f28c360600340879b35`; the second applies `portable-gpu.patch`. The source revision is fetched by layerctl, so the first composition requires network access. No source Git archive is bundled.

From the project root, run:

```sh
(cd vendor/360DVO && ../../scripts/layerctl.sh check)
(cd vendor/360DVO && ../../scripts/layerctl.sh projection create portable --worktree /absolute/path/to/new-worktree)
```

A fresh checkout must first initialize this definition directory as a Git repository; `install-macos.sh` does that for the Apple runtime. The projection target must not exist. The patch provides inference on full equirectangular frames; seam behavior remains unvalidated.
