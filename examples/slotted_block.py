"""Synthetic slotted block: the dimensions do not describe a real cooler adapter."""

from solidrecipe import Box

slot_height = 4.6
model = Box(12, 30, 10) - Box(9, 20, slot_height, origin=(-1, 5, 2))

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("height", type=float, nargs="?", default=slot_height)
    parser.add_argument("output", nargs="?", default="graph.json")
    args = parser.parse_args()
    model = Box(12, 30, 10) - Box(9, 20, args.height, origin=(-1, 5, 2))
    model.write_graph(args.output)
