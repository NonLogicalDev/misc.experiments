#!/usr/bin/env python3
"""Check that candidate review inputs and sheets are unchanged; never approve them."""
import argparse
from pathlib import Path
from review_candidates import verify

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('review_manifest', type=Path)
args = p.parse_args()
verify(args.review_manifest)
print('Review inputs and sheets match; human review and approval are still required.')
