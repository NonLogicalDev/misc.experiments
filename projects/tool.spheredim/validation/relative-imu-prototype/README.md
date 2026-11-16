# Experimental spherical and IMU residuals

This CPU reference tests full-equirectangular reprojection with simulated relative orientation measurements. It creates no perspective views. It has known synthetic scale and truth-perturbed initial points, so it is not a real-footage solver. Its visual residual wraps the panorama seam; orientation residuals use the SO(3) logarithm with a robust loss and an explicit assumed uncertainty.

Run the structural tests with the uv-managed portable environment:

```sh
uv run --isolated --no-project --python 3.14 --with-requirements ../../vendor/360DVO/requirements-macos-arm64-py314.lock python test_diagnostic.py
```

The tests exercise connected, weak-baseline, disconnected, biased-IMU and noisy-IMU cases. Neither the visual-only nor the IMU-regularized solves reached convergence in the initial 600-evaluation tests, and a connected run also failed to converge after 3,000 evaluations. These tests validate bounded behavior and diagnostics, not solver accuracy. Do not use this reference to change a real camera trajectory until its convergence, Jacobians, calibration, uncertainty, and failure cases are validated.
