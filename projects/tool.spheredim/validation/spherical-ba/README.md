# Synthetic spherical bundle adjustment

These CPU diagnostics generate full-equirectangular camera observations directly, with known camera poses and points. They test fixed-intrinsics Ceres bundle adjustment using a single global similarity alignment against known truth, with independent tracks re-triangulated under each candidate trajectory. They do not extract perspective views.

From this directory, using the project's uv-managed PyCOLMAP environment:

```sh
uv run --isolated --no-project --python 3.14 --with-requirements ../../requirements.txt python test_regressions.py
```

The suite verifies improvement on a connected observable synthetic scene and demonstrates that held-out reprojection can improve while globally aligned pose accuracy gets worse on disconnected scenes. Additional generator options cover noisy initialized geometry, low parallax, outliers and short tracks. Passing the suite is not evidence that an unconverged real-footage solution is reliable or that the user’s accuracy target has been met.
