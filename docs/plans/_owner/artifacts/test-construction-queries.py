"""Experiment with construction-based queries on the real adapter.

The model is instrumented in memory with names for the primitive inputs. The
existing debug CLI evaluates each stage and returns its real face provenance and
edge uses. This is a research harness, not the SolidRecipe query API. Assertions
are deliberately independent of the proposed source/adjacency expressions.
No Rust build or persistent generated output is needed.
"""

import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SOURCE = ROOT / "examples/cooler_adapter.py"


def replace_once(source, old, new):
    if source.count(old) != 1:
        raise RuntimeError(f"Expected one occurrence: {old!r}")
    return source.replace(old, new)


def instrument():
    source = SOURCE.read_text()
    replacements = [
        ("shape = block(0, 0, 0, 12.5, 71, 8.5)",
         'shape = block(0, 0, 0, 12.5, 71, 8.5).with_metadata(id="base")'),
        ("shape += block(0, raised_start, 8.5, 12.5, raised_length, 4.5)",
         'shape += block(0, raised_start, 8.5, 12.5, raised_length, 4.5).with_metadata(id="raised")'),
        ("shape += block(0, 0, 8.5, 3, raised_start, 3.5)",
         'shape += block(0, 0, 8.5, 3, raised_start, 3.5).with_metadata(id="strip")'),
        ("shape -= block(-1, 8, 7.4 - slot_height, 10, 46, slot_height)",
         'shape -= block(-1, 8, 7.4 - slot_height, 10, 46, slot_height).with_metadata(id="groove")'),
        ("shape -= block(-0.1, -0.1, -0.1, 1.1, 71.2, 7.5 - slot_height)",
         'shape -= block(-0.1, -0.1, -0.1, 1.1, 71.2, 7.5 - slot_height).with_metadata(id="setback")'),
        ("shape -= sr.Cylinder(1.75, 9, origin=(hole_x, y, -0.1))",
         'shape -= sr.Cylinder(1.75, 9, origin=(hole_x, y, -0.1)).with_metadata(id=f"hole-{y}")'),
        ("        if entry_fillets:\n", "        snapshots.append(('entry', shape))\n        if entry_fillets:\n"),
        ("        if underside_chamfer:\n", "        snapshots.append(('chamfer', shape))\n        if underside_chamfer:\n"),
        ("        return shape.with_metadata(\n", "        snapshots.append(('final', shape))\n        return shape.with_metadata(\n"),
    ]
    for old, new in replacements:
        source = replace_once(source, old, new)
    namespace = {"__name__": "construction_query_probe", "snapshots": []}
    exec(compile(source, str(SOURCE), "exec"), namespace)
    return namespace


def inspect(shape):
    proc = subprocess.run(
        [str(ROOT / "target/debug/solidrecipe"), "inspect-graph"],
        input=json.dumps(shape.node), text=True, capture_output=True, check=True,
    )
    return json.loads(proc.stdout)


def from_source(report, feature, role):
    return {
        f["index"] for f in report["faces"]
        if any(i.get("feature") == feature and i.get("role") == role
               for i in f.get("identities", [f.get("identity") or {}]))
    }


def edges_of(report, faces):
    return {e["index"] for e in report["edges"] if any(f in faces for f in e["adjacent_faces"])}


def between(report, a, b):
    # Distinct incident faces are essential: a cylinder seam has uses [f, f].
    return {e["index"] for e in report["edges"]
            if any(x != y and x in a and y in b
                   for x in e["adjacent_faces"] for y in e["adjacent_faces"])}


def possible_source(report, feature, role):
    """A conservative experiment, conditional on the reported per-face flags.

    SolidRecipe does not yet certify completeness of the history, so these are
    diagnostic bounds, not production guarantees.
    """
    certain = from_source(report, feature, role)
    unknown = {f["index"] for f in report["faces"]
               if f.get("origin_status") == "generated or untracked"}
    return certain, certain | unknown


def near(a, b):
    return abs(a - b) < 1e-6


def is_segment(edge, p, q):
    def point_matches(actual, expected):
        return all(near(a, b) for a, b in zip(actual, expected))
    return edge["curve"]["kind"] == "line" and (
        (point_matches(edge["start"], p) and point_matches(edge["end"], q)) or
        (point_matches(edge["start"], q) and point_matches(edge["end"], p)))


def geometry_segments(report, segments):
    return {e["index"] for e in report["edges"] if any(is_segment(e, a, b) for a, b in segments)}


def test_case(side, height, stage, report):
    role = {"left": ("x_min", "x_max"), "right": ("x_max", "x_min")}[side]
    inside, inner = role
    src = lambda feature, face: from_source(report, feature, face)
    base_bottom = src("base", "z_min")
    groove_back = src("groove", inner)
    groove_floor = src("groove", "z_min")
    groove_roof = src("groove", "z_max")
    groove_ends = src("groove", "y_min") | src("groove", "y_max")
    result = {"side": side, "height": height, "stage": stage,
              "untracked_faces": [f["index"] for f in report["faces"]
                                  if f.get("origin_status") == "generated or untracked"]}
    if stage == "entry":
        selected = between(report, src("base", inside), groove_ends)
        x = 0 if side == "left" else 12.5
        expected = geometry_segments(report, [((x, y, 7.4 - height), (x, y, 7.4)) for y in (8, 54)])
        assert len(expected) == 2, (side, height, stage, expected)
        result["entry"] = {"query": sorted(selected), "expected": sorted(expected), "match": selected == expected}
    if stage in ("chamfer", "final"):
        wall = groove_back
        selection = edges_of(report, wall) - between(report, wall, groove_floor)
        if stage == "final":
            x = 9 if side == "left" else 3.5
            floor, roof = 7.4 - height, 7.4
            segments = [((x, 8, floor), (x, 8, roof)), ((x, 8, roof), (x, 54, roof)),
                        ((x, 54, floor), (x, 54, roof))]
            expected = geometry_segments(report, segments)
            assert len(expected) == 3, (side, height, stage, expected)
            result["user_slot_geometry"] = {"query": sorted(selection), "expected": sorted(expected), "match": selection == expected}
            positive = between(report, groove_back, groove_roof) | between(report, groove_back, groove_ends)
            result["slot_authored_sides"] = {"query": sorted(positive), "expected": sorted(expected), "match": positive == expected}
            if side == "left" and height == 4.6:
                assert expected == {6, 9, 16}, expected
            back_lo, back_hi = possible_source(report, "groove", inner)
            floor_lo, floor_hi = possible_source(report, "groove", "z_min")
            certain = edges_of(report, back_lo) - between(report, back_hi, floor_hi)
            possible = edges_of(report, back_hi) - between(report, back_lo, floor_lo)
            result["slot_diagnostic_bounds"] = {"certain": sorted(certain), "possible": sorted(possible),
                                                "caveat": "conditional on unverified history completeness"}
            top, raised, strip = src("base", "z_max"), src("raised", "y_min"), src("strip", inner)
            pairwise = between(report, top, raised) | between(report, top, strip) | between(report, raised, strip)
            corner = (3 if side == "left" else 9.5, 10.85 if side == "left" else 10.8, 8.5)
            expected = {e["index"] for e in report["edges"] if any(
                all(near(a, b) for a, b in zip(endpoint, corner)) for endpoint in (e["start"], e["end"]))}
            assert len(expected) == 3, (side, height, stage, expected)
            if side == "left" and height == 4.6:
                assert expected == {35, 36, 43}, expected
            result["corner_pairwise_geometry"] = {"query": sorted(pairwise), "expected": sorted(expected), "match": pairwise == expected,
                                                  "caveat": "coincident endpoints are not verified shared vertices"}
        if stage == "chamfer":
            selected = between(report, src("setback", inner), base_bottom)
            x = 1 if side == "left" else 11.5
            expected = geometry_segments(report, [((x, 0, 0), (x, 71, 0))])
            assert len(expected) == 1, (side, height, stage, expected)
            result["setback"] = {"query": sorted(selected), "expected": sorted(expected), "match": selected == expected}
            walls = src("hole-5.5", "side") | src("hole-65.5", "side")
            selected = between(report, walls, {f["index"] for f in report["faces"]} - walls)
            x = 9.225527 if side == "left" else 3.725527
            expected = {e["index"] for e in report["edges"] if e["curve"]["kind"] == "circle"
                        and near(e["curve"]["radius"], 1.75)
                        and near(e["curve"]["frame"]["origin"][0], x)
                        and any(near(e["curve"]["frame"]["origin"][1], y) for y in (5.5, 65.5))
                        and any(near(e["curve"]["frame"]["origin"][2], z) for z in (0, 8.5))}
            assert len(expected) == 4, (side, height, stage, expected)
            result["hole_rims"] = {"query": sorted(selected), "expected": sorted(expected), "match": selected == expected}
            bottom = between(report, walls, base_bottom)
            expected_bottom = {e["index"] for e in report["edges"] if e["index"] in expected
                               and near(e["curve"]["frame"]["origin"][2], 0)}
            assert len(expected_bottom) == 2, (side, height, expected_bottom)
            result["bottom_rims"] = {"query": sorted(bottom), "expected": sorted(expected_bottom),
                                     "match": bottom == expected_bottom}
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--side", choices=("left", "right"))
    parser.add_argument("--height", type=float)
    parser.add_argument("--stage", choices=("entry", "chamfer", "final"))
    args = parser.parse_args()
    ns = instrument()
    failures = []
    for side, height in (("left", 4.5), ("left", 4.6), ("left", 4.7), ("right", 4.5), ("right", 4.7)):
        if (args.side and args.side != side) or (args.height is not None and args.height != height):
            continue
        ns["snapshots"].clear()
        ns["adapter"](side=side, slot_height=height)
        for stage, shape in ns["snapshots"]:
            if args.stage and args.stage != stage:
                continue
            try:
                result = test_case(side, height, stage, inspect(shape))
            except subprocess.CalledProcessError as exc:
                result = {"side": side, "height": height, "stage": stage,
                          "inspection_error": exc.stderr.strip()}
                failures.append(result)
            print(json.dumps(result), flush=True)
            failures.extend(v for v in result.values() if isinstance(v, dict) and v.get("match") is False)
    if failures:
        raise SystemExit(f"{len(failures)} experiment(s) failed")


if __name__ == "__main__":
    main()
