"""Run alternating GPU kernel samples from two prebuilt tile harnesses."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import statistics
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline', type=Path)
    parser.add_argument('candidate', type=Path)
    parser.add_argument('output', type=Path, help='New JSON result path')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output already exists')
    digests = [hashlib.sha256(path.read_bytes()).hexdigest() for path in (args.baseline, args.candidate)]
    if digests[0] == digests[1]:
        parser.error('Baseline and candidate executables are identical')
    print(f'Executable SHA-256: baseline={digests[0]} candidate={digests[1]}', flush=True)
    rows = []
    for width in (1024, 2048):
        for mode in (0, 1, 2):
            for repeat in range(2):
                order = [('baseline', args.baseline), ('candidate', args.candidate)]
                if repeat:
                    order.reverse()
                for label, executable in order:
                    if shutil.disk_usage(args.output.parent).free < 35 * 1024**3:
                        raise RuntimeError('Less than 35 GiB free')
                    result = subprocess.run([str(executable), '--bench', str(width), str(mode)], capture_output=True, text=True, timeout=120, check=True)
                    samples = [float(value) for value in result.stdout.splitlines() if value.strip()]
                    if len(samples) != 10 or any(value <= 0 for value in samples):
                        raise ValueError(f'Invalid GPU timestamp samples: {result.stdout} {result.stderr}')
                    row = {'width': width, 'mode': mode, 'repeat': repeat, 'variant': label, 'executable_sha256': digests[0 if label == 'baseline' else 1], 'gpu_ms': samples, 'median_ms': statistics.median(samples)}
                    rows.append(row)
                    print(row, flush=True)
    with args.output.open('x') as output:
        json.dump(rows, output, indent=2)
        output.write('\n')


if __name__ == '__main__':
    main()
