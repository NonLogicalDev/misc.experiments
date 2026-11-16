# 360DVO real-camera sample

This sample is derived from the `tokyo_citywalk` sequence in [360DVO](https://huggingface.co/datasets/chris1004336379/360DVO), by Xiaopeng Guo, Yinzhe Xu, Huajian Huang, and Sai-Kit Yeung, licensed [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/). It contains every second image from source frames 0001 through 0099, encoded at 5 fps. `manifest.json` records input paths, hashes, and the encoding parameters. `tokyo-reference.txt` is the authors' reference trajectory and `tokyo-poses.json` is SphereDim's result. The reference was reconstructed using Agisoft Metashape; it is not an independently measured trajectory.

To recompute the reported position metrics from the saved result:

```sh
uv run --isolated --no-project --python 3.14 --with-requirements requirements.txt python tests/evaluate_real.py validation/real/tokyo-reference.txt validation/real/tokyo-poses.json 2
```

The subset does not include an independent depth map or known 3D points, so it cannot establish image alignment error. The video was re-encoded and no other visual modification was applied. The data and derived video are subject to the dataset's noncommercial share-alike license; this does not apply to SphereDim source code.

