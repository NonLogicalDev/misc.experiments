"""Check the 1% trajectory and per-frame image alignment targets."""
import json
import sys
from pathlib import Path
from evaluate import evaluate

if len(sys.argv) != 4:
    raise SystemExit('Usage: check_accuracy.py truth.json poses.json imported.json')
truth, poses, imported = [json.loads(Path(p).read_text()) for p in sys.argv[1:]]
report = evaluate(truth, poses, imported)
print(json.dumps(report, indent=2))
if report['registered'] != report['sampled']:
    raise SystemExit('FAIL: one or more sampled frames are unregistered')
if report['image_sampled_frames'] != report['sampled']:
    raise SystemExit('FAIL: missing ground-truth image samples in one or more frames')
if report['position_rmse_percent_path'] >= 1 or report['image_worst_frame_p95_percent'] >= 1:
    raise SystemExit('FAIL: trajectory RMS or a frame image p95 meets or exceeds 1%')
print('PASS: complete registration, trajectory RMS and every frame image p95 below 1%')
