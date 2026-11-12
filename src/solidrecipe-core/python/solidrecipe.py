"""Code-first shape graphs and in-process geometry queries."""

import functools
import itertools
import json
import math
import sys
from contextlib import contextmanager
from pathlib import Path

# Occurrences only distinguish authored nodes within one serialized graph. They
# are deliberately not persistent feature IDs and can change on each rebuild.
_occurrences = itertools.count()


def _entity_identities(entity):
    """Collect the reported origins, including the legacy singular field.

    Transforms may preserve a null singular field for generated entities, while a
    merge reports several origins. Neither form should be treated as a unique ID.
    """
    identities = []
    for identity in (entity.get("identities") or []) + [entity.get("identity")]:
        if isinstance(identity, dict) and identity not in identities:
            identities.append(identity)
    return identities


def _resolve_entity(
    items, matches_identity, description, multiple_error, missing_error=None
):
    """Return one unmerged descendant, or report why selection is unsafe."""
    matches = [
        (item, identities)
        for item in items
        if (identities := _entity_identities(item))
        and any(matches_identity(identity) for identity in identities)
    ]
    if not matches:
        if missing_error is not None:
            raise ValueError(missing_error)
        raise ValueError(f"{description} is missing or identity is unavailable")
    if len(matches) > 1:
        raise ValueError(f"{description} {multiple_error}")
    item, identities = matches[0]
    if len(identities) > 1 or item.get("merged"):
        raise ValueError(f"{description} is merged with other identities")
    return item


class Shape:
    """Immutable-style expression node; operators compose graphs without evaluating geometry."""

    def __init__(self, node):
        self.node = {**node, "occurrence": next(_occurrences)}

    def __sub__(self, other):
        return Shape({"kind": "subtract", "left": self.node, "right": other.node})

    def __add__(self, other):
        return Shape({"kind": "union", "left": self.node, "right": other.node})

    def __and__(self, other):
        return Shape({"kind": "intersect", "left": self.node, "right": other.node})

    def measure(self):
        """Measure this shape's current B-rep for use in later model calculations."""
        return measure(self)

    def face(self, role):
        """Return current face data for a named box role such as `z_max`."""
        data = inspect_data(self)
        return _resolve_entity(
            data["faces"],
            lambda identity: identity.get("role") == role,
            f"face {role!r}",
            "is ambiguous or split",
        )

    def edge(self, first_face, second_face):
        """Return the named box edge between two face roles, with its measured length."""
        roles = sorted([first_face, second_face])
        data = inspect_data(self)
        return _resolve_entity(
            data["edges"],
            lambda identity: identity.get("roles") == roles,
            f"edge {roles!r}",
            "is ambiguous or split",
        )

    def face_ref(self, role):
        """Return the unique persistent reference for a named box face role."""
        return _entity_identities(self.face(role))[0]

    def edge_between_faces(self, first_face, second_face):
        """Return the edge reference where two named box faces meet.

        For example, `x_min` and `y_min` name the lowest-X and lowest-Y faces.
        """
        return _entity_identities(self.edge(first_face, second_face))[0]

    def resolve(self, identity):
        """Resolve an exact face or edge identity on the current shape.

        Unsupported operations and missing or ambiguous identities fail explicitly.
        """
        if not isinstance(identity, dict) or identity.get("kind") not in (
            "face",
            "edge",
        ):
            raise ValueError("expected a face or edge identity from inspect_data")
        data = inspect_data(self)
        items = data["faces" if identity["kind"] == "face" else "edges"]
        if identity in (data.get("tracked_identities") or []):
            missing_error = "no surviving tracked descendant; deleted or untracked"
        else:
            missing_error = "identity is unknown or unavailable"
        return _resolve_entity(
            items,
            lambda candidate: candidate == identity,
            "identity",
            "is split or ambiguous",
            missing_error,
        )

    def translate(self, x, y, z):
        """Return a copy placed by the given X, Y and Z offsets in millimeters."""
        return Shape({"kind": "translate", "body": self.node, "offset": [x, y, z]})

    def scale(self, x, y=None, z=None):
        """Scale about the origin: one factor uniformly, or three factors by axis."""
        if y is None and z is None:
            y = z = x
        elif y is None or z is None:
            raise ValueError("scale takes one factor or three axis factors")
        return Shape({"kind": "scale", "body": self.node, "factors": [x, y, z]})

    def instance(self, name):
        """Declare a named instance boundary around this shape's graph.

        The name is a persistent namespace component chosen by the model author;
        node occurrence tokens only distinguish objects during graph evaluation.
        """
        if not isinstance(name, str) or not name.strip():
            raise ValueError("instance name must be a nonempty string")
        return Shape({"kind": "instance", "name": name, "body": self.node})

    def _blend(self, kind, size, edge_points, edge_refs, tolerance):
        """Build one blend node with exactly one edge-selection method."""
        if (edge_points is None) == (edge_refs is None):
            raise ValueError("provide either edge_points or edge_refs")
        node = {"kind": kind, "body": self.node, "size": size}
        if edge_refs is not None:
            if not isinstance(edge_refs, (list, tuple)) or not edge_refs:
                raise ValueError("edge_refs must be a nonempty sequence of identities")
            if any(
                not isinstance(identity, dict) or identity.get("kind") != "edge"
                for identity in edge_refs
            ):
                raise ValueError("edge_refs must contain edge identities")
            # Copy the references: a caller changing a result dictionary later must
            # not silently retarget an already constructed graph.
            node["edge_identities"] = json.loads(json.dumps(edge_refs, allow_nan=False))
        else:
            node["points"] = edge_points
            node["tolerance"] = tolerance
        return Shape(node)

    def fillet(self, *, radius, edge_points=None, edge_refs=None, tolerance=0.01):
        """Round edges selected by persistent identities or model-space points.

        Points are geometric selectors, not persistent topology identities. A rebuild
        fails if any point identifies no edge or more than one edge within tolerance.
        Pass edge identity dictionaries from inspection as `edge_refs`; resolution
        fails if an identity is missing, split, merged, or ambiguous.
        """
        return self._blend("fillet", radius, edge_points, edge_refs, tolerance)

    def chamfer(self, *, distance, edge_points=None, edge_refs=None, tolerance=0.01):
        """Bevel selected edges with equal setbacks, using identities or points."""
        return self._blend("chamfer", distance, edge_points, edge_refs, tolerance)

    def with_metadata(self, **metadata):
        """Return a shape whose graph node carries JSON-serializable author metadata.

        Metadata belongs to this node, not automatically to faces made from it.
        An `id` on a box names its semantic face and edge identities; other
        metadata and IDs on other node kinds do not create topology identities.
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


def Line(a, b):
    """A directed 2D profile segment, from point `a` to point `b`."""
    return {"type": "line", "a": list(a), "b": list(b)}


def Arc(center, radius, start, sweep):
    """A directed circular profile arc; angles are in radians."""
    return {
        "type": "arc",
        "center": list(center),
        "radius": radius,
        "start": start,
        "sweep": sweep,
    }


def CubicBezier(start, control1, control2, end):
    """An exact cubic Bézier profile segment defined by its four control points."""
    return {
        "type": "cubic",
        "p0": list(start),
        "p1": list(control1),
        "p2": list(control2),
        "p3": list(end),
    }


def CatmullRom(points, *, closed=False):
    """Interpolate 2D fit points with connected, uniform Catmull–Rom cubics.

    Returns exact cubic Bézier segments. Open curves use repeated endpoint
    neighbors; closed curves wrap. This is a specified interpolation rule, not
    a claim to reproduce Fusion's fit-point spline algorithm.
    """
    points = [tuple(point) for point in points]
    if len(points) < (3 if closed else 2) or any(
        len(point) != 2
        or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in point)
        for point in points
    ):
        raise ValueError(
            "CatmullRom needs finite 2D points: at least two, or three when closed"
        )
    count = len(points)

    def point(i):
        return points[i % count] if closed else points[max(0, min(i, count - 1))]

    segments = []
    for i in range(count if closed else count - 1):
        before, start, end, after = (point(i - 1), point(i), point(i + 1), point(i + 2))
        control1 = [start[j] + (end[j] - before[j]) / 6 for j in range(2)]
        control2 = [end[j] - (after[j] - start[j]) / 6 for j in range(2)]
        segments.append(CubicBezier(start, control1, control2, end))
    return segments


def Polygon(points):
    """A closed, directed loop of straight segments through the given 2D points."""
    points = [list(point) for point in points]
    if len(points) < 3:
        raise ValueError("a polygon needs at least three points")
    return [
        Line(point, points[(index + 1) % len(points)])
        for index, point in enumerate(points)
    ]


def Circle(center, radius, *, clockwise=False):
    """A complete circular loop; use clockwise=True when it forms a hole."""
    return [Arc(center, radius, 0, -math.tau if clockwise else math.tau)]


class Plane:
    """A sketch coordinate frame in 3D; its normal is `x_dir` × `y_dir`.

    Give any two perpendicular unit directions; the third follows the
    right-hand rule. With no directions, the plane uses the world XY frame.
    """

    def __init__(self, *, origin=(0, 0, 0), x_dir=None, y_dir=None, z_dir=None):
        directions = [d for d in (x_dir, y_dir, z_dir) if d is not None]
        if not directions:
            x_dir, y_dir = (1, 0, 0), (0, 1, 0)
        elif len(directions) != 2:
            raise ValueError("specify any two plane directions")
        else:
            a, b = map(tuple, directions)
            if any(
                len(d) != 3
                or any(
                    not isinstance(v, (int, float)) or not math.isfinite(v) for v in d
                )
                for d in (a, b)
            ):
                raise ValueError(
                    "plane directions must contain three finite coordinates"
                )
            if (
                any(abs(sum(v * v for v in d) - 1) > 1e-9 for d in (a, b))
                or abs(sum(x * y for x, y in zip(a, b, strict=True))) > 1e-9
            ):
                raise ValueError("plane directions must be perpendicular unit vectors")

            def cross(u, v):
                return (
                    u[1] * v[2] - u[2] * v[1],
                    u[2] * v[0] - u[0] * v[2],
                    u[0] * v[1] - u[1] * v[0],
                )

            if x_dir is None:
                x_dir = cross(a, b)  # Y × Z
            elif y_dir is None:
                y_dir = cross(b, a)  # Z × X
        self.origin = tuple(origin)
        self.x_dir = tuple(x_dir)
        self.y_dir = tuple(y_dir)

    def _record(self):
        return {"origin": self.origin, "x_dir": self.x_dir, "y_dir": self.y_dir}


def _plane_record(plane):
    if isinstance(plane, Plane):
        return plane._record()
    if isinstance(plane, str):
        plane = plane.upper()
        if plane in ("XY", "XZ", "YZ"):
            return plane
    # Preserve compatibility with authored graphs using the original mapping.
    if isinstance(plane, dict):
        return plane
    raise ValueError("plane must be XY, XZ, YZ or a Plane")


class Profile:
    """A planar region with a directed outer loop and optional hole loops.

    Loops are connected sequences of `Line`, `Arc`, and `CubicBezier` segments,
    or those returned by `Polygon`, `Circle`, and `CatmullRom`. The outer loop must be counterclockwise and holes
    clockwise in the plane's coordinates. `plane` is XY, XZ, YZ, or a `Plane`
    with an origin and orthonormal `x_dir` and `y_dir` vectors. The plane's
    positive normal is x_dir × y_dir. The kernel validates closure and geometry.
    """

    def __init__(self, outer, *, holes=(), plane="XY"):
        plane = _plane_record(plane)
        # Own the profile data: later mutations of the caller's lists must not
        # retarget an extrusion already constructed from it.
        self._data = json.loads(
            json.dumps(
                {
                    "region": {
                        "outer": {"segs": list(outer)},
                        "holes": [{"segs": list(h)} for h in holes],
                    },
                    "plane": plane,
                },
                allow_nan=False,
            )
        )

    def extrude(self, distance):
        """Extrude the region along its positive normal by a positive distance."""
        if (
            not isinstance(distance, (int, float))
            or not math.isfinite(distance)
            or distance <= 0
        ):
            raise ValueError("extrusion distance must be finite and positive")
        return Shape(
            {
                "kind": "extrude",
                **json.loads(json.dumps(self._data)),
                "distance": distance,
            }
        )


class Sketch:
    """Curves on a plane; crossings divide the drawing into closed regions.

    Region selection uses a point strictly inside the desired region. The
    point and original curves stay in the graph and are evaluated again when
    the model is built. Curve order is not a persistent identity.
    """

    def __init__(self, curves, *, plane="XY"):
        plane = _plane_record(plane)
        self._data = json.loads(
            json.dumps({"curves": list(curves), "plane": plane}, allow_nan=False)
        )

    def profile_at(self, point):
        """Select one region by an interior point in sketch coordinates.

        Point containment uses the sketch engine's sampled outlines; avoid
        choosing a point close to a boundary.
        """
        if len(point) != 2 or any(
            not isinstance(v, (int, float)) or not math.isfinite(v) for v in point
        ):
            raise ValueError("profile point must contain two finite coordinates")
        return _SketchProfile(self._data, point)

    def offset(self, curves, distance):
        """Add an offset of an ordered, directed chain of authored curves.

        Positive distance is to the left of the direction of the chain. The
        original curves remain in the sketch. The source chain must identify
        unique curves; duplicate coincident records are ambiguous.
        """
        if (
            not isinstance(distance, (int, float))
            or not math.isfinite(distance)
            or distance == 0
        ):
            raise ValueError("offset distance must be finite and nonzero")
        indices = []
        for curve in curves:
            matches = [
                i
                for i, candidate in enumerate(self._data["curves"])
                if candidate == curve
            ]
            if len(matches) != 1:
                raise ValueError(
                    "each offset source must identify exactly one sketch curve"
                )
            indices.append(matches[0])
        if not indices or len(set(indices)) != len(indices):
            raise ValueError("offset needs a nonempty chain without repeated curves")
        result = Sketch(self._data["curves"], plane=self._data["plane"])
        result._data["offsets"] = [
            *self._data.get("offsets", []),
            {"curves": indices, "distance": distance},
        ]
        return result


class _SketchProfile:
    def __init__(self, sketch, point):
        self._data = json.loads(json.dumps({**sketch, "point": list(point)}))

    def extrude(self, distance):
        """Extrude the selected closed region along its plane normal."""
        if (
            not isinstance(distance, (int, float))
            or not math.isfinite(distance)
            or distance <= 0
        ):
            raise ValueError("extrusion distance must be finite and positive")
        return Shape(
            {
                "kind": "extrude",
                **json.loads(json.dumps(self._data)),
                "distance": distance,
            }
        )


class Bounds:
    """Axis-aligned B-rep bounds, in millimeters."""

    def __init__(self, minimum, maximum):
        self.minimum = tuple(minimum)
        self.maximum = tuple(maximum)

    @property
    def size(self):
        return tuple(hi - lo for lo, hi in zip(self.minimum, self.maximum, strict=True))

    @property
    def center(self):
        return tuple(
            (lo + hi) / 2 for lo, hi in zip(self.minimum, self.maximum, strict=True)
        )


class Measurements:
    """B-rep measurements for one evaluated shape; volume is in cubic millimeters."""

    def __init__(self, result):
        self.bounds = Bounds(result["bounds"]["min"], result["bounds"]["max"])
        self.volume = result["volume"]


def measure(shape):
    """Evaluate and measure a prior shape in-process; this currently builds it anew."""
    if not isinstance(shape, Shape):
        raise TypeError("measure expects a solidrecipe Shape")
    if _measure_graph is None:
        raise RuntimeError("measure requires the embedded SolidRecipe runtime")
    return Measurements(json.loads(_measure_graph(json.dumps(shape.node))))


def inspect_data(shape):
    """Return rich B-rep details; face and edge indices apply only to this result."""
    if not isinstance(shape, Shape):
        raise TypeError("inspect_data expects a solidrecipe Shape")
    if _inspect_graph is None:
        raise RuntimeError("inspect_data requires the embedded SolidRecipe runtime")
    record = json.loads(_inspect_graph(json.dumps(shape.node)))
    record["graph"] = shape.node
    return record


def inspect(shape, name=None):
    """Print one JSONL B-rep inspection record to stderr; indices are not persistent."""
    record = inspect_data(shape)
    record["name"] = name
    print(
        json.dumps(record, separators=(",", ":"), allow_nan=False),
        file=sys.stderr,
        flush=True,
    )


# The embedded Rust host installs these in-process B-rep bridges.
_inspect_graph = None
_measure_graph = None


# The embedded host resets this registry before each model evaluation.
_parameter_values = {}
_parameter_specs = {}
_export_frames = [{}]
_module_stack = []
_loaded_files = {}


def _begin_parameters(values):
    global _parameter_values, _parameter_specs
    _parameter_values = values
    _parameter_specs = {}
    _export_frames.clear()
    _module_stack.clear()
    _loaded_files.clear()


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
    if not isinstance(description, str) or (
        unit is not None and not isinstance(unit, str)
    ):
        raise TypeError(f"description and unit must be strings: {name}")
    if any(
        x is not None and (type(x) not in (int, float) or not math.isfinite(x))
        for x in (minimum, maximum, step)
    ):
        raise ValueError(f"bounds and step must be finite numbers: {name}")
    if numeric and not math.isfinite(default):
        raise ValueError(f"default must be finite: {name}")
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
    if options is not None:
        for index, option in enumerate(options):
            valid = (
                (type(option) in (int, float) and math.isfinite(option))
                if numeric
                else type(option) is type(default)
            )
            if not valid or any(option == other for other in options[:index]):
                raise ValueError(
                    f"options must have distinct values of the parameter type: {name}"
                )
    if (minimum is not None and default < minimum) or (
        maximum is not None and default > maximum
    ):
        raise ValueError(f"default outside bounds: {name}")
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


_MISSING_EXPORT = object()


def export(name_or_value, value=_MISSING_EXPORT):
    """Export a named shape or callable, or export one value as the default.

    `sr.export(shape)` exposes a default; `sr.export(function)` uses its
    function name. Exports belong only to the current file and module scope.
    """
    if not _export_frames:
        raise RuntimeError("export must be called while evaluating a SolidRecipe file")
    if value is _MISSING_EXPORT:
        value = name_or_value
        name = (
            getattr(value, "__name__", None)
            if callable(value) and not isinstance(value, Shape)
            else "default"
        )
    else:
        name = name_or_value
    if not isinstance(name, str) or not name.isidentifier():
        raise ValueError("export name must be a Python identifier")
    if not isinstance(value, Shape) and not callable(value):
        raise TypeError("an export must be a Shape or a callable")
    exports = _export_frames[-1]
    if name in exports:
        raise ValueError(f"duplicate export: {name!r}")
    if callable(value) and not isinstance(value, Shape):
        # Functions keep their defining file as the base for nested relative loads,
        # even when a different model invokes them later.
        owner = (
            _module_stack[-1]
            if _module_stack
            else Path(getattr(value, "__globals__", {}).get("__file__", ".")).resolve()
        )
        original = value

        @functools.wraps(original)
        def bound(*args, **kwargs):
            _module_stack.append(owner)
            try:
                return original(*args, **kwargs)
            finally:
                _module_stack.pop()

        value = bound
    exports[name] = value
    return value


def exportf(function_or_name=None):
    """Export a function as a decorator, inferring its name unless one is supplied.

    Use `@sr.exportf`, `@sr.exportf()` or `@sr.exportf("name")`.
    """
    if callable(function_or_name):
        return export(function_or_name)
    if function_or_name is None:
        return lambda function: export(function)
    if isinstance(function_or_name, str):
        return lambda function: export(function_or_name, function)
    raise TypeError("exportf expects a function or an export name")


def _evaluate_file(path, source=None):
    path = Path(path).resolve()
    if path in _module_stack:
        raise ValueError(f"circular SolidRecipe module load: {path}")
    # Record the exact bytes used so the Rust watcher detects edits during a build.
    _loaded_files[str(path)] = None
    if source is None:
        source = path.read_bytes().decode("utf-8")
    _loaded_files[str(path)] = source
    _module_stack.append(path)
    exports = {}
    _export_frames.append(exports)
    directory = str(path.parent)
    sys.path.insert(0, directory)
    try:
        namespace = {"__name__": "__solidrecipe_model__", "__file__": str(path)}
        exec(compile(source, str(path), "exec"), namespace)
        # Existing single-model files remain valid until explicitly migrated.
        if not exports and isinstance(namespace.get("model"), Shape):
            exports["default"] = namespace["model"]
        return exports
    finally:
        sys.path.remove(directory)
        _export_frames.pop()
        _module_stack.pop()


class ModuleExports:
    """Read-only namespace of shapes, factories and nested modules from one file."""

    def __init__(self, values):
        self._values = values

    def __getitem__(self, name):
        value = self._values[name]
        return ModuleExports(value) if isinstance(value, dict) else value

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as error:
            raise AttributeError(name) from error


@contextmanager
def module(name):
    """Group exports under a namespace; multiple modules may share a file."""
    if not _export_frames:
        raise RuntimeError(
            "module must be declared while evaluating a SolidRecipe file"
        )
    if not isinstance(name, str) or not name.isidentifier():
        raise ValueError("module name must be a Python identifier")
    parent = _export_frames[-1]
    if name in parent:
        raise ValueError(f"duplicate export or module: {name!r}")
    namespace = {}
    parent[name] = namespace
    _export_frames.append(namespace)
    try:
        yield ModuleExports(namespace)
    finally:
        _export_frames.pop()


def load(path):
    """Load a SolidRecipe file and return its file-scoped named exports.

    Relative paths resolve against the file currently being evaluated. Values are
    shapes or callables; callables can build parameterized shapes in the caller.
    """
    base = _module_stack[-1].parent if _module_stack else Path.cwd()
    return ModuleExports(_evaluate_file(base / path))


class Param:
    """Optional viewer metadata for a function parameter in typing.Annotated."""

    def __init__(
        self,
        *,
        description="",
        unit=None,
        minimum=None,
        maximum=None,
        step=None,
        options=None,
    ):
        self.description = description
        self.unit = unit
        self.minimum = minimum
        self.maximum = maximum
        self.step = step
        self.options = options
