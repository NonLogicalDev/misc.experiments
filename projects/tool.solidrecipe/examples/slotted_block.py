"""Synthetic slotted block: the dimensions do not describe a real cooler adapter."""

import solidrecipe as sr

slot_height = 4.6
model = sr.Box(12, 30, 10) - sr.Box(9, 20, slot_height, origin=(-1, 5, 2))

if __name__ == "__main__":
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("height", type=float, nargs="?", default=slot_height)
    parser.add_argument("output", nargs="?", default=".work/artifacts/graph.json")
    args = parser.parse_args()
    model = sr.Box(12, 30, 10) - sr.Box(9, 20, args.height, origin=(-1, 5, 2))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    model.write_graph(str(output))
