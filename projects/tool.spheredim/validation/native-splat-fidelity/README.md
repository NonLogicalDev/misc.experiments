# Analytic native-ERP plane fixture

`prepare_analytic_plane.py NEW_DIRECTORY` makes five full 768×384 equirectangular RGB observations with exact camera poses and masks of a finite textured plane, plus an exact-plane XYZ/RGB seed. Three captures are training inputs and two are held out. The rest of each ERP image is masked; no perspective or cubemap images are generated. This is synthetic pipeline validation and must not be presented as measured real-scene geometry.

The fixture evaluates rays at pixel centers, intersects only positive rays with the finite z=3 plane, and uses the same deterministic chart for image pixels and seed colors. `manifest.json` records camera poses, source hashes and intersection checks. The current 0.16-unit chart-cell projection sampled across the five cameras has a minimum singular value of 4.19 pixels; this is a sampled check rather than a proven global bound.

Run `python -m unittest -v test_analytic_plane` from this directory with NumPy and OpenCV available. Generate data in a new task-scoped directory; training settings, resource limits, output checks and comparisons must be specified separately before a GPU run.

`compare_analytic_plane.py DIRECTORY` compares the two held-out renders in the directory's `zero` and `fit` subdirectories. It checks that their masks match the source mask and their ground truth matches the source image, then writes `comparison.json` and source/zero/fit crop images to that directory. Run it only when those output files may be replaced.

A perfect match has zero MSE and infinite PSNR; `valid_psnr` is `null` in JSON for that case.
