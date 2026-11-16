# X5 IMU and per-frame orientation extractor

This prototype extracts raw IMU readings and computed gravity-aligned orientations from an Insta360 X5 INSV. Tested with one X5 file; other models, timestamp schemes, multiple files, reordered frames, and clips with missing or inconsistent timing are not supported. Check downstream results before use. It does not obtain position or absolute compass heading. The IMU fusion is estimated; yaw can drift. FFprobe packet PTS must be strictly increasing. The source file is read only; output files must not already exist.

Requires Rust 1.90 or later, Cargo, Git, and FFmpeg's `ffprobe` on PATH. The Cargo manifest pins `insta360-rs` to the inspected public git commit; Cargo.lock pins transitive dependencies. Build downloads code and package resources from the public Git repository and registry. Your local INSV is never sent to those sources. Binary build products belong outside version control.

```sh
cargo build --release --locked
cargo run --release --locked -- /absolute/path/input.insv /absolute/path/new-output-directory
```

The output directory contains `imu_fused.csv` and `orientation_frames_fused.csv`. The former contains per-sample accelerometer (`*_g`), angular velocity (`*_rad_s`), IMU camera clock microseconds, and estimated w/x/y/z quaternion. The latter contains video PTS seconds, exposure-aligned camera-clock microseconds, the fused per-frame quaternion, and relative heading radians. Quaternion is body-to-world with gravity world +Z. Camera body axes from raw sensor are `(raw_y, raw_z, raw_x)`. Capture times account for exposure and camera gyro offset. This assumes the timing mode present in the verified X5 sample; verify against a new model/file.

For a FlowState export with rolling-shutter correction off, the output-to-input body ray rotation is `R_fused.transpose() @ Rz(heading)`. Rolling shutter correction makes a spatially varying warp that a single rotation cannot capture. This ray map was checked against short exports of the tested X5 recording; see the companion mask and pose scripts.

The Rust source is Apache-2.0, but the upstream NOTICE states that its `insta360-rs-data-*` resources include SDK/Studio assets under their original terms. Review upstream licensing before redistribution; the Cargo dependency fetches those packages even with default features disabled.
