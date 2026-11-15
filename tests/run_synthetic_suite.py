"""Render, track, import and evaluate varied native-panorama test scenes."""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from evaluate import evaluate

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ('plain', 'repetitive', 'low_light')


def invoke(args, log):
    with log.open('w') as stream:
        return subprocess.run([str(arg) for arg in args], stdout=stream, stderr=subprocess.STDOUT).returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path, help='new or empty results directory')
    parser.add_argument('--blender', default='blender')
    parser.add_argument('--encoder', default='ffmpeg', help='FFmpeg with H.264 encoder for test-video generation')
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        parser.error('Output directory must be absent or empty')
    if not shutil.which(args.blender) or not shutil.which(args.encoder):
        parser.error('Blender and an FFmpeg with libx264 are required')
    args.output.mkdir(parents=True, exist_ok=True)
    summary = {}
    for scenario in SCENARIOS:
        case = args.output / scenario
        case.mkdir()
        frames = case / 'render'
        code = invoke([args.blender, '--background', '--factory-startup', '--python', ROOT/'tests/render_scene.py', '--', frames, scenario], case/'render.log')
        if code or not (frames/'truth.json').is_file():
            summary[scenario] = {'status':'render_failed', 'exit_code':code}
            continue
        video = case/'input.mp4'
        noise = 4 if scenario == 'low_light' else 2
        code = invoke([args.encoder, '-hide_banner', '-loglevel', 'error', '-framerate', '8', '-i', frames/'%06d.png', '-vf', f'lenscorrection=k1=0.003:k2=0,noise=alls={noise}:allf=t+u', '-c:v', 'libx264', '-crf', '16', '-pix_fmt', 'yuv420p', video], case/'encode.log')
        if code:
            summary[scenario] = {'status':'encode_failed', 'exit_code':code}
            continue
        output = case/'tracking'
        code = invoke([sys.executable, ROOT/'src/spheredim.py', video, output, '--width', '1024'], case/'tracking.log')
        if code or not (output/'poses.json').exists():
            summary[scenario] = {'status':'tracking_failed', 'exit_code':code}
            continue
        imported = case/'imported'
        code = invoke([args.blender, '--background', '--factory-startup', '--python', ROOT/'tests/check_import.py', '--', ROOT/'src/blender_import.py', output/'poses.json', imported], case/'import.log')
        if code or not imported.with_suffix('.json').exists():
            summary[scenario] = {'status':'import_failed', 'exit_code':code}
            continue
        truth, poses, matrices = [json.loads(p.read_text()) for p in (frames/'truth.json', output/'poses.json', imported.with_suffix('.json'))]
        try:
            metrics = evaluate(truth, poses, matrices)
            passed = (metrics['registered'] == metrics['sampled'] == metrics['image_sampled_frames'] and metrics['position_rmse_percent_path'] < 1 and metrics['image_worst_frame_p95_percent'] < 1)
            summary[scenario] = {'status':'pass' if passed else 'accuracy_failed', 'metrics':metrics}
        except ValueError as error:
            summary[scenario] = {'status':'evaluation_failed', 'reason':str(error)}
        (args.output/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    (args.output/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    print(json.dumps(summary, indent=2))
    if any(item['status'] != 'pass' for item in summary.values()):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
