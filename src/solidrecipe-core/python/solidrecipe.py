"""Experimental language frontend: write a graph; do not invoke a kernel or viewer."""

import json
from pathlib import Path


class Shape:
    def __init__(self, node):
        self.node = node

    def __sub__(self, other):
        return Shape({"kind": "subtract", "left": self.node, "right": other.node})

    def __add__(self, other):
        return Shape({"kind": "union", "left": self.node, "right": other.node})

    def __and__(self, other):
        return Shape({"kind": "intersect", "left": self.node, "right": other.node})

    def write_graph(self, path):
        Path(path).write_text(json.dumps(self.node, indent=2) + "\n")


def Box(x, y, z, origin=(0, 0, 0)):
    return Shape({"kind": "box", "size": [x, y, z], "origin": list(origin)})
