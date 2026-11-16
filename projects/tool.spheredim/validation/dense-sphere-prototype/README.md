# Experimental spherical dense matching

This CPU-only research prototype tests inverse-depth patch matching directly on full equirectangular images. It does not extract perspective views. It is not a production dense-reconstruction pipeline and is not established to work accurately on real footage. `native.py` also contains an earlier optical-flow experiment that failed the synthetic depth check; do not use that path for reconstruction.

Run the synthetic checks from this directory using the uv-managed portable 360DVO environment:

```sh
for test_case in test_geometry.py test_synthetic.py test_occlusion.py test_noisy.py test_textureless.py; do
  uv run --isolated --no-project --python 3.14 --with-requirements ../../vendor/360DVO/requirements-macos-arm64-py314.lock python "$test_case" || exit 1
done
```

The tests cover ray geometry, a textured plane, a two-depth occlusion case, modest image noise and exposure change, and rejection of a textureless scene. On the initial Apple CPU test, median depth error was 1.1–1.6% and p95 4.7–5.9% for the nonempty synthetic cases. Those simple cases do not establish the project accuracy target. A ten-group real-video probe yielded inconsistent fourth-view color agreement, not an independent depth accuracy measurement. The prototype still needs general pose/mask input, occlusion handling, difficult seam and pole cases, confidence calibration, and a cross-vendor GPU backend.
