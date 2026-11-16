"""Recover a sparse camera trajectory from complete equirectangular video frames."""
import argparse
import csv
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path
from fractions import Fraction

import pycolmap


def run(video: Path, output: Path, fps: float | None, width: int, overlap: int) -> None:
    if not video.is_file():
        raise ValueError(f"Video does not exist: {video}")
    if fps is not None and (not math.isfinite(fps) or fps <= 0):
        raise ValueError("Sampling rate must be positive and finite")
    if width < 256 or width % 2:
        raise ValueError("Width must be even and at least 256 pixels")
    if overlap < 1:
        raise ValueError("Overlap must be at least 1")
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"Output directory is not empty: {output}")
    runtime = Path(__file__).resolve().parent.parent / '.artifacts' / 'ffmpeg-runtime' / 'bin'
    ffmpeg = str(runtime / 'ffmpeg') if (runtime / 'ffmpeg').is_file() else shutil.which('ffmpeg')
    ffprobe = str(runtime / 'ffprobe') if (runtime / 'ffprobe').is_file() else shutil.which('ffprobe')
    if not ffmpeg or not ffprobe:
        raise ValueError('Build the vendored FFmpeg or install ffmpeg and ffprobe on PATH')
    probe = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,avg_frame_rate", "-of", "json", str(video)], capture_output=True, text=True, check=True)
    streams = json.loads(probe.stdout)["streams"]
    if not streams or streams[0]["width"] != 2 * streams[0]["height"]:
        raise ValueError("Expected a full 2:1 equirectangular video")
    if fps is None:
        try:
            fps = float(Fraction(streams[0]['avg_frame_rate']))
        except (KeyError, ValueError, ZeroDivisionError):
            raise ValueError('Cannot determine video frame rate; specify --fps') from None
        if not math.isfinite(fps) or fps <= 0:
            raise ValueError('Cannot determine video frame rate; specify --fps')
    output.mkdir(parents=True, exist_ok=True)
    frames = output / "frames"
    frames.mkdir()
    # fps produces a constant-rate timeline; do not use it to claim original VFR timestamps.
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(video), "-vf", f"fps={fps},scale={width}:{width // 2}", "-compression_level", "3", "-start_number", "0", str(frames / "%06d.png")], check=True)
    names = sorted(p.name for p in frames.glob("*.png"))
    if len(names) < 3:
        raise ValueError("Video produced fewer than three sampled frames")
    db = output / "database.db"
    sparse = output / "sparse"
    sparse.mkdir()
    reader = pycolmap.ImageReaderOptions(camera_model="EQUIRECTANGULAR")
    extraction = pycolmap.FeatureExtractionOptions(num_threads=4)
    pycolmap.extract_features(db, frames, camera_mode=pycolmap.CameraMode.SINGLE, reader_options=reader, extraction_options=extraction, device=pycolmap.Device.cpu)
    pairing = pycolmap.SequentialPairingOptions(overlap=overlap)
    matching = pycolmap.FeatureMatchingOptions(num_threads=4)
    pycolmap.match_sequential(db, matching_options=matching, pairing_options=pairing, device=pycolmap.Device.cpu)
    options = pycolmap.IncrementalPipelineOptions(multiple_models=True, min_model_size=3, num_threads=4)
    options.mapper.init_min_tri_angle = 4.0
    # Tighten geometric outlier rejection for pose precision on full panoramas.
    options.mapper.filter_max_reproj_error = 2.0
    options.mapper.abs_pose_max_error = 6.0
    options.mapper.init_max_error = 2.0
    models = pycolmap.incremental_mapping(db, frames, sparse, options=options)
    if not models:
        raise ValueError("No reconstruction found; try more texture, translation, or a different sampling rate")
    # Disconnected reconstructions cannot be combined into one coordinate system.
    model_id, model = max(models.items(), key=lambda item: item[1].num_reg_images())
    poses = {}
    for image in model.images.values():
        if not image.has_pose:
            continue
        world_from_camera = image.cam_from_world().inverse().matrix()
        poses[image.name] = world_from_camera.tolist()
    if len(poses) < 3:
        raise ValueError("Fewer than three camera poses were registered")
    rows = []
    for index, name in enumerate(names):
        rows.append({"frame": index, "time_seconds": index / fps, "image": name, "world_from_camera": poses.get(name)})
    result = {"schema": "spheredim-poses-v1", "input_video": str(video.resolve()), "sampling_fps": fps, "camera_model": "COLMAP EQUIRECTANGULAR", "coordinates": "camera-to-world 3x4 row-major; camera x right, y down, z forward; arbitrary world axes and scale", "selected_model": model_id, "registered": len(poses), "sampled": len(names), "frames": rows}
    (output / "poses.json").write_text(json.dumps(result, indent=2) + "\n")
    with (output / "poses.csv").open("w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["frame", "time_seconds", "image", "registered"] + [f"m{r}{c}" for r in range(3) for c in range(4)])
        for row in rows:
            matrix = row["world_from_camera"]
            writer.writerow([row["frame"], row["time_seconds"], row["image"], int(matrix is not None)] + ([v for line in matrix for v in line] if matrix else [""] * 12))
    print(f"Registered {len(poses)}/{len(names)} frames; poses: {output / 'poses.json'}")
    if len(poses) != len(names):
        print("Some frames are unregistered; see poses.json. Other disconnected models are in sparse/.", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("output", type=Path, help="new or empty output directory")
    parser.add_argument("--fps", type=float, default=None, help="sample rate (default: source average frame rate)")
    parser.add_argument("--width", type=int, default=2048, help="panorama width (default: 2048)")
    parser.add_argument("--overlap", type=int, default=10, help="sequential frame matching window")
    args = parser.parse_args()
    try:
        run(args.video, args.output, args.fps, args.width, args.overlap)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"SphereDim: {error}\n")


if __name__ == "__main__":
    main()
