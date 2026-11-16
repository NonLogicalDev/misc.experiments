# /// script
# requires-python = ">=3.10"
# dependencies = ["insta360-rs==0.2.1"]
# ///
"""Stitch an Insta360 recording on a GPU with horizon leveling and preserved yaw."""
import argparse
import sys
import time
from pathlib import Path

import insta360_rs as ins


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--width', type=int, default=2048, help='Equirectangular output width (height is half)')
    parser.add_argument('--duration', type=float, help='Limit output duration in seconds')
    parser.add_argument('--stabilization', choices=('flow-state', 'off'), default='flow-state', help='FlowState levels the horizon while retaining yaw')
    parser.add_argument('--rolling-shutter', choices=('off', 'auto'), default='off', help='Use off for a single frame-level mask transform')
    parser.add_argument('--audio', choices=('copy', 'drop'), default='copy')
    args = parser.parse_args()
    if not args.input.is_file():
        parser.error('Input recording does not exist')
    if args.output.exists():
        parser.error('Output already exists')
    if args.width < 128 or args.width % 2:
        parser.error('Width must be an even number of at least 128')
    if args.duration is not None and args.duration <= 0:
        parser.error('Duration must be positive')
    config = ins.StitchConfig(
        backend=ins.ProcessingBackend.GPU,
        stabilization={'flow-state': ins.Stabilization.FLOW_STATE, 'off': ins.Stabilization.OFF}[args.stabilization],
        rolling_shutter={'off': ins.RollingShutterCorrection.OFF, 'auto': ins.RollingShutterCorrection.AUTO}[args.rolling_shutter],
        width=args.width, height=args.width // 2,
    )
    job = ins.start_export_video(str(args.input), str(args.output), config=config, quality=90,
        audio={'copy': ins.AudioPolicy.COPY, 'drop': ins.AudioPolicy.DROP}[args.audio], duration=args.duration)
    while not job.is_finished():
        progress = job.progress()
        if progress is not None:
            print(f'{progress.phase} {progress.completed}/{progress.total} elapsed={progress.elapsed_seconds:.1f}s remaining={progress.estimated_remaining_seconds}', flush=True)
        time.sleep(2)
    result = job.wait()
    print(f'Complete: {result.frames_written} frames in {result.elapsed_seconds:.1f}s; backend={result.backend.selected}; outputs={result.outputs}', flush=True)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
