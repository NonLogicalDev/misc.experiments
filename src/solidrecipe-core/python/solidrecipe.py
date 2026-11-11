"""Experimental language frontend: write a graph; do not invoke a kernel or viewer."""

import json
import os
import shutil
import subprocess
import sys
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

    def with_metadata(self, **metadata):
        """Return a shape whose graph node carries JSON-serializable author metadata.

        Metadata belongs to this node, not automatically to faces made from it.
        Names and labels are useful for later provenance, but are not stable topology IDs.
        """
        # Validate early rather than letting a rebuild fail while writing the graph.
        json.dumps(metadata, allow_nan=False)
        node = {**self.node, "metadata": {**self.node.get("metadata", {}), **metadata}}
        return Shape(node)

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


def inspect(shape, name=None):
    """Print one JSONL B-rep inspection record to stderr; indices are not persistent.

    The CLI supplies its executable path in live previews. When executing a model
    directly, put solidrecipe on PATH or set SOLIDRECIPE_CLI to that executable.
    """
    if not isinstance(shape, Shape):
        raise TypeError("inspect expects a solidrecipe Shape")
    cli = os.environ.get("SOLIDRECIPE_CLI") or shutil.which("solidrecipe")
    if not cli:
        raise RuntimeError("inspect requires solidrecipe on PATH or SOLIDRECIPE_CLI")
    result = subprocess.run(
        [cli, "inspect-graph"],
        input=json.dumps(shape.node),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"inspect failed: {result.stderr.strip()}")
    record = json.loads(result.stdout)
    record["name"] = name
    record["graph"] = shape.node
    print(
        json.dumps(record, separators=(",", ":"), allow_nan=False),
        file=sys.stderr,
        flush=True,
    )
