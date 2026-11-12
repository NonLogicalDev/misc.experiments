"""Evaluate Python model source inside SolidRecipe's embedded interpreter."""

import inspect
import json
import traceback
from typing import Annotated, get_args, get_origin, get_type_hints


def _outputs(exports, prefix=""):
    import solidrecipe as sr

    result = {}
    for name, item in exports.items():
        full_name = f"{prefix}.{name}" if prefix else name
        if isinstance(item, dict):
            result.update(_outputs(item, full_name))
        elif isinstance(item, sr.Shape) or callable(item):
            result[full_name] = item
    return result


def _evaluate_callable(factory):
    import solidrecipe as sr

    signature = inspect.signature(factory)
    hints = get_type_hints(inspect.unwrap(factory), include_extras=True)
    values = {}
    for name, argument in signature.parameters.items():
        if argument.kind not in (argument.POSITIONAL_OR_KEYWORD, argument.KEYWORD_ONLY):
            raise ValueError(f"Preview parameter {name!r} must be a named argument")
        if argument.default is argument.empty:
            raise ValueError(f"Preview parameter {name!r} needs a default value")
        annotation = hints.get(name, argument.annotation)
        base = (
            get_args(annotation)[0]
            if get_origin(annotation) is Annotated
            else annotation
        )
        metadata = (
            next(
                (
                    item
                    for item in get_args(annotation)[1:]
                    if isinstance(item, sr.Param)
                ),
                None,
            )
            if get_origin(annotation) is Annotated
            else None
        )
        default = (
            float(argument.default)
            if base is float and type(argument.default) is int
            else argument.default
        )
        attrs = vars(metadata) if metadata else {}
        values[name] = sr.parameter(name, default, **attrs)
    shape = factory(**values)
    if not isinstance(shape, sr.Shape):
        raise TypeError(
            "An exported module function must return a SolidRecipe Shape for preview"
        )
    return shape


def evaluate_source(path, source, overrides, selected=None):
    """Return one selected output, its parameters and exact source dependencies."""
    import solidrecipe as sr

    sr._begin_parameters(json.loads(overrides))
    try:
        exports = _outputs(sr._evaluate_file(path, source))
        if not exports:
            raise ValueError(
                "File has no output; call sr.export(shape) or sr.export(name, factory)."
            )
        selected = (
            selected
            if selected in exports
            else ("default" if "default" in exports else next(iter(exports)))
        )
        item = exports[selected]
        shape = item if isinstance(item, sr.Shape) else _evaluate_callable(item)
        unknown = set(sr._parameter_values) - set(sr._parameter_specs)
        if unknown:
            raise ValueError(
                f"Unknown parameters for {selected!r}: {', '.join(sorted(unknown))}"
            )
        result = {
            "outputs": list(exports),
            "output": selected,
            "graph": shape.node,
            "parameters": sr._parameter_definitions(),
        }
    except Exception:
        # Preserve the dependency list even when a child is missing or has an error.
        result = {"error": traceback.format_exc()}
    result["sources"] = sr._loaded_files
    return json.dumps(result, allow_nan=False)
