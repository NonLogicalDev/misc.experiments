"""Experimental language frontend: write a graph; do not invoke a kernel or viewer."""

import json
from pathlib import Path


class Shape:
    """Immutable-style expression node; operators compose graphs without evaluating geometry."""

    def __init__(self, node):
        self.node = node

    def __sub__(self, other):
        return Shape({"kind": "subtract", "left": self.node, "right": other.node})

    def __add__(self, other):
        return Shape({"kind": "union", "left": self.node, "right": other.node})

    def __and__(self, other):
        return Shape({"kind": "intersect", "left": self.node, "right": other.node})

    def write_graph(self, path):
        """Serialize the graph for the CLI and SolidCore evaluator."""
        Path(path).write_text(json.dumps(self.node, indent=2) + "\n")


def Box(x, y, z, origin=(0, 0, 0)):
    """Create an axis-aligned box node from its size and minimum corner."""
    return Shape({"kind": "box", "size": [x, y, z], "origin": list(origin)})


def Cylinder(radius, height, origin=(0, 0, 0)):
    """Create a Z-axis cylinder whose origin is the center of its bottom face."""
    return Shape(
        {"kind": "cylinder", "radius": radius, "height": height, "origin": list(origin)}
    )
