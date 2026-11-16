# Experimental native 360 pose and splat comparison

Two 3,000-step Vulkan GPU training runs used the same 133 full 1024×512 equirectangular frames, reviewed operator masks, 22,774-point SfM seed, training settings and 116/17 train/evaluation split. The only intended change was camera poses: tight-mask SfM versus 360DVO poses similarity-aligned to the SfM coordinate system. Rendering stayed spherical; no perspective views were extracted. The 17 saved ground-truth images are byte-identical across arms. The initialization favors SfM because the seed came from its reconstruction. A fixed sampling seed does not imply deterministic GPU execution.

| Masked unaligned metric, mean over 17 frames | SfM poses | 360DVO poses |
| --- | ---: | ---: |
| PSNR, dB | 21.329 | 19.088 |
| SSIM | 0.7739 | 0.7167 |
| L1 | 0.06430 | 0.07800 |

SfM had higher PSNR on 15/17 frames and higher SSIM on 17/17. Mean paired PSNR difference was 2.241 dB. This measures rendering quality in this setup, not ground-truth pose accuracy. The evaluation images were held out from splat training but contributed to the pose estimation and SfM seed, so this is not an independent held-out pose test. The limited training and visibly soft renders do not establish good-quality splats or a trajectory accuracy target.

The source selection included 138 reviewed samples. Four did not register in the SfM reconstruction. One further camera, frame_001785.png at approximately 59.56 seconds, was excluded from both derived arms because its orientation jumped 39.61 degrees from the prior registered pose and 27.2 degrees to the next, while the corresponding DVO changes were 7.12 and 10.13 degrees. The original model is unmodified. Masks were visually reviewed at reduced resolution and may have small leaks or false positives; intermediate video frames were not reviewed.

The run logs, final 3,000-step checkpoints, render and ground-truth images, metrics, configs, dataset manifests, and preparation/training scripts are preserved beside this report. Configuration files retain their original temporary input paths as provenance; point them at the preserved datasets to rerun. See the separate tight-mask SfM A/B report for SfM counts, mask guards, and descriptor-boundary limitations.
