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


# A fresh evaluation process owns this registry; it is reset for direct evaluator calls too.
_parameter_values = {}
_parameter_specs = {}


def _begin_parameters(values):
    global _parameter_values, _parameter_specs
    _parameter_values = values
    _parameter_specs = {}


def _parameter_definitions():
    return list(_parameter_specs.values())


def parameter(
    name,
    default,
    *,
    description="",
    unit=None,
    minimum=None,
    maximum=None,
    step=None,
    options=None,
):
    """Declare a model parameter and return its current value.

    Values can be bool, number or string. Bounds and units describe numeric values;
    options restrict a value to one of the provided choices. `step` is a UI hint.
    Names are unique within a model and remain the key used by saved presets.
    """
    if not isinstance(name, str) or not name or name in _parameter_specs:
        raise ValueError(f"parameter name must be nonempty and unique: {name!r}")
    if type(default) not in (bool, int, float, str):
        raise TypeError(f"unsupported default for parameter {name!r}")
    numeric = type(default) in (int, float)
    if any(x is not None for x in (minimum, maximum, step)) and not numeric:
        raise ValueError(f"bounds and step require a numeric parameter: {name}")
    if step is not None and (
        not isinstance(step, (int, float)) or isinstance(step, bool) or step <= 0
    ):
        raise ValueError(f"step must be positive: {name}")
    if minimum is not None and maximum is not None and minimum > maximum:
        raise ValueError(f"minimum exceeds maximum: {name}")
    if options is not None and (
        not isinstance(options, list) or not options or default not in options
    ):
        raise ValueError(
            f"options must be a nonempty list containing the default: {name}"
        )
    value = _parameter_values.get(name, default)
    if type(default) is bool:
        valid_type = type(value) is bool
    elif numeric:
        valid_type = type(value) in (int, float) and not (
            type(default) is int and type(value) is float and not value.is_integer()
        )
        if valid_type and type(default) is int:
            value = int(value)
    else:
        valid_type = isinstance(value, str)
    if (
        not valid_type
        or (minimum is not None and value < minimum)
        or (maximum is not None and value > maximum)
        or (options is not None and value not in options)
    ):
        raise ValueError(f"invalid value for parameter {name!r}: {value!r}")
    spec = {
        "name": name,
        "default": default,
        "value": value,
        "description": description,
        "unit": unit,
        "minimum": minimum,
        "maximum": maximum,
        "step": step,
        "options": options,
    }
    json.dumps(spec, allow_nan=False)
    _parameter_specs[name] = spec
    return value
