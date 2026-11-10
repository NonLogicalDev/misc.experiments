"""Synthetic slotted block: the dimensions do not describe a real cooler adapter."""
import argparse

from solidrecipe import Box

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("height", type=float, nargs="?", default=4.6)
parser.add_argument("output", nargs="?", default="graph.json")
args = parser.parse_args()
result = Box(12, 30, 10) - Box(9, 20, args.height, origin=(-1, 5, 2))
result.write_graph(args.output)
