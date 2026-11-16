# Display-only perspective parity fixture

`tools/native-sfm/prepare_display_parity.py` prepares a 512×512 perspective image and a two-row COLMAP input from one physical ERP capture. It does not run training or render a model. Supply a new output directory, the source RGB and operator mask, the source COLMAP `images.txt` and exact image name, the preserved splat PLY and its SHA-256, and the existing seed PLY:

```sh
python tools/native-sfm/prepare_display_parity.py --image ERP.png --mask MASK.png --images-txt images.txt --image-name SOURCE_NAME --ply MODEL.ply --ply-sha256 MODEL_SHA256 --seed SEED.ply --aim X_CENTER Y_CENTER --size 512 --fov-y 55 --out NEW_DIRECTORY
```

`--aim` is an ERP pixel-center coordinate: integer pixel `(x,y)` has center `(x+0.5,y+0.5)`. Perspective rays use center sampling, CV right/down/forward and the case JSON also records the equivalent OpenGL right/up/back camera-to-world matrix. The image is bilinearly sampled from decoded sRGB with longitude wrap. A pixel is valid only if all four source mask samples are 255; invalid output pixels are black. The resulting train/eval image aliases are only for a zero-update renderer check. They must not be used as reconstruction training or SfM data.

For a native comparison, use the saved PLY in its original world gauge with identity scene transform, full SH degree 3, a black background, appearance corrections off, zero iterations, and no checkpoint save. Match focal length, resolution, camera matrix and display color handling against `case.json`; compare only its valid mask and do not align images. A renderer mismatch is not automatically evidence of reconstruction error.

Focused tests: `python -m unittest -v test_prepare_display_parity` from `tools/native-sfm`, with the repository's existing NumPy and OpenCV environment.
