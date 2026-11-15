# Portable 360DVO validation

All runs used the portable tensor implementation on Apple MPS, width 1024 and 96 patches per frame. No perspective images were extracted. The synthetic captures are the existing SphereDim Blender scenes. Their pose files were imported through `tests/check_import.py`; `blender.json` contains the actual matrices Blender produced. `tests/evaluate.py` uses one similarity alignment and independently ray-cast visible scene points to measure trajectory and image displacement. Image displacement normalizes x and y by their respective dimensions, and the per-frame p95 is the 95th percentile of point displacement on each frame.

| Sequence | Frames | Position RMS / path | Worst-frame image p95 | Reference |
| --- | ---: | ---: | ---: | --- |
| loop | 48 | 0.153% | 1.669% | Synthetic Blender scene |
| dynamic | 32 | 0.145% | 1.270% | Synthetic scene with a moving object |
| plain | 24 | 3.332% | 32.791% | Low-texture Blender scene |
| bridge_night | 40 | 0.369% | Not measured | 360DVO SfM-derived reference |
| grove | 40 | 0.115% | Not measured | 360DVO SfM-derived reference |
| indoor_RC_car | 40 | 0.077% | Not measured | 360DVO SfM-derived reference |

All three synthetic image p95 values exceed the 1% per-frame target. Counts mean output poses; the network may infer poses for removed frames from relative motion. For the real footage, `tests/evaluate_real.py` uses every second reference frame; the reference is not independent measured ground truth. Scene inputs and truth are in the adjacent `validation/loop`, `validation/dynamic`, and `validation/complexity` directories. Outputs are recorded here as run, including their original input paths. These short clips do not establish long-sequence accuracy or AMD support.
