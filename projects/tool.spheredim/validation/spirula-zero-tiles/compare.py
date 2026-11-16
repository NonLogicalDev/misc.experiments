"""Compare two outputs from the zero-tile GPU parity harness."""
import argparse
import math
from pathlib import Path
import struct


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline', type=Path)
    parser.add_argument('candidate', type=Path)
    args = parser.parse_args()
    raw = [path.read_bytes() for path in (args.baseline, args.candidate)]
    if len(raw[0]) != len(raw[1]) or len(raw[0]) != 194112:
        raise ValueError('Unexpected output length')
    a, b = [struct.unpack(f'<{len(data) // 4}f', data) for data in raw]
    failures = 0
    maximum = 0.0
    for original, candidate in zip(a, b):
        if not math.isfinite(original) or not math.isfinite(candidate):
            failures += not (math.isnan(original) and math.isnan(candidate)) and original != candidate
            continue
        difference = abs(original - candidate)
        maximum = max(maximum, difference)
        failures += difference > 1e-5 + 1e-4 * abs(original)
    print(f'{len(a)} values; {failures} mismatches; max absolute difference {maximum:g}')
    if failures:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
