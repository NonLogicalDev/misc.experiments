"""Exercise source and incidence queries on several real SolidCore B-reps.

Uses existing inspect-graph executable and named primitive identities. This is a
research experiment; inspect-graph does not certify provenance completeness.
"""

import json
import subprocess
from pathlib import Path

import solidrecipe as sr

ROOT = Path(__file__).resolve().parents[4]


def named(solid, name):
    return solid.with_metadata(id=name)


def inspect(shape):
    proc = subprocess.run([str(ROOT / "target/debug/solidrecipe"), "inspect-graph"],
                          input=json.dumps(shape.node), text=True, capture_output=True, check=True)
    return json.loads(proc.stdout)


def source(report, feature, role=None):
    return {f["index"] for f in report["faces"]
            if any(i.get("feature") == feature and (role is None or i.get("role") == role)
                   for i in f.get("identities", [f.get("identity") or {}]))}


def between(report, a, b):
    return {e["index"] for e in report["edges"]
            if any(x != y and x in a and y in b
                   for x in e["adjacent_faces"] for y in e["adjacent_faces"])}


def check(name, shape, tool, expected_count, seam_expected=False, levels=None):
    data = inspect(shape)
    wall = source(data, tool, "side" if tool.startswith("bore") else None)
    other = {f["index"] for f in data["faces"]} - wall
    result = between(data, wall, other)
    seam = {e["index"] for e in data["edges"]
            if len(e["adjacent_faces"]) == 2 and e["adjacent_faces"][0] == e["adjacent_faces"][1]
            and e["adjacent_faces"][0] in wall}
    assert len(result) == expected_count, (name, result)
    assert not (seam & result), (name, seam, result)
    if seam_expected:
        assert seam, name
        curves = [e["curve"] for e in data["edges"] if e["index"] in result]
        assert all(c["kind"] == "circle" for c in curves), (name, curves)
        if levels is not None:
            assert sorted(c["frame"]["origin"][2] for c in curves) == levels, (name, curves)
    elif levels is not None:
        selected = [e for e in data["edges"] if e["index"] in result]
        actual_levels = sorted(e["start"][2] for e in selected)
        assert all(e["curve"]["kind"] == "line" and e["start"][2] == e["end"][2]
                   for e in selected), (name, selected)
        assert actual_levels == levels, (name, actual_levels)
    print(json.dumps({"case": name, "tool_faces": sorted(wall), "interface": sorted(result),
                      "expected_count": expected_count, "count_matches": len(result) == expected_count,
                      "seams": sorted(seam), "seams_excluded": not bool(seam & result),
                      "expected_seam_present": bool(seam) if seam_expected else None,
                      "untracked_faces": [f["index"] for f in data["faces"]
                                          if f.get("origin_status") == "generated or untracked"]}), flush=True)


def check_split_and_merge():
    stock = named(sr.Box(10, 10, 5), "split-stock")
    notch = named(sr.Box(2, 2, 7, origin=(4, -1, -1)), "notch")
    data = inspect(stock - notch)
    children = [e for e in data["edges"] if any(
        i.get("feature") == "split-stock" and i.get("roles") == ["y_min", "z_max"]
        for i in e.get("identities", []))]
    spans = sorted(sorted((e["start"][0], e["end"][0])) for e in children)
    assert spans == [[0.0, 4.0], [6.0, 10.0]], spans
    print(json.dumps({"case": "source edge split by notch", "children": [e["index"] for e in children],
                      "x_spans": spans, "same_source_identity": True}), flush=True)

    left = named(sr.Box(10, 10, 5), "left")
    right = named(sr.Box(5, 10, 5, origin=(10, 0, 0)), "right")
    data = inspect(left + right)
    left_top = source(data, "left", "z_max")
    right_top = source(data, "right", "z_max")
    far_end = source(data, "right", "x_max")
    assert left_top == right_top and len(left_top) == 1, (left_top, right_top)
    misleading = between(data, left_top, far_end)
    edges = [e for e in data["edges"] if e["index"] in misleading]
    assert len(edges) == 1 and all(p[0] == 15 for p in (edges[0]["start"], edges[0]["end"]))
    print(json.dumps({"case": "coplanar union merges source faces", "left_top": sorted(left_top),
                      "right_top": sorted(right_top), "far_end_edge": sorted(misleading),
                      "far_end_x": 15, "original_left_extent_x": [0, 10],
                      "lesson": "entity ancestry does not label a local portion of a merged face"}), flush=True)


def check_half_interface_fillet():
    stock = named(sr.Box(12, 10, 5), "stock")
    cutter = named(sr.Box(4, 4, 7, origin=(3, 3, -1)), "cutter")
    shape = stock - cutter
    before = inspect(shape)
    walls = source(before, "cutter")
    top = between(before, walls, source(before, "stock", "z_max"))
    bottom = between(before, walls, source(before, "stock", "z_min"))
    assert len(top) == len(bottom) == 4 and not (top & bottom), (top, bottom)
    selected = [e for e in before["edges"] if e["index"] in top]
    assert all(e["start"][2] == 5 and e["end"][2] == 5 for e in selected)
    # The query engine is not implemented: transfer the selected edges through
    # the existing point-picking API, not as a claim of a direct query-to-blend API.
    after = inspect(shape.fillet(edge_points=[e["midpoint"] for e in selected], radius=0.2))
    lower = between(after, source(after, "cutter"), source(after, "stock", "z_min"))
    assert len(lower) == 4 and all(e["start"][2] == e["end"][2] == 0
                                   for e in after["edges"] if e["index"] in lower)
    assert after["volume"] < before["volume"]
    print(json.dumps({"case": "fillet one half of rectangular Boolean interface",
                      "top_edges": sorted(top), "bottom_edges": sorted(bottom),
                      "bottom_edges_after": sorted(lower), "volume_before": before["volume"],
                      "volume_after": after["volume"],
                      "handoff": "snapshot edge midpoints through existing point picker"}), flush=True)


def check_pairwise_corner_counterexample():
    stock = named(sr.Box(10, 10, 5), "stock")
    notch = named(sr.Box(2, 2, 2, origin=(-1, 4, 4)), "notch")
    data = inspect(stock - notch)
    a, b, c = (source(data, "stock", role) for role in ("x_min", "y_min", "z_max"))
    pairwise = between(data, a, b) | between(data, a, c) | between(data, b, c)
    # Endpoint equality is only an independent geometric oracle here. The
    # inspection report does not expose shared topological vertex IDs.
    at_corner = {e["index"] for e in data["edges"]
                 if [0.0, 0.0, 5.0] in (e["start"], e["end"])}
    assert len(pairwise) == 4 and len(at_corner) == 3 and at_corner < pairwise
    print(json.dumps({"case": "notch splits an edge away from the chosen corner",
                      "pairwise_face_query": sorted(pairwise), "corner_endpoint_oracle": sorted(at_corner),
                      "extra_edges": sorted(pairwise - at_corner),
                      "caveat": "topological vertex incidence not checked by inspection"}), flush=True)


def check_boolean_operations():
    first = named(sr.Box(10, 10, 10), "first")
    second = named(sr.Box(10, 4, 4, origin=(5, 3, 3)), "second")
    for name, shape in (("cut", first - second), ("union", first + second),
                        ("intersection", first & second)):
        data = inspect(shape)
        a, b = source(data, "first"), source(data, "second")
        selected = between(data, a, b)
        # Each operation leaves a four-edge interface on x=10 for this geometry.
        geometry = {e["index"] for e in data["edges"] if e["curve"]["kind"] == "line"
                    and e["start"][0] == e["end"][0] == 10
                    and all(3 <= p[1] <= 7 and 3 <= p[2] <= 7 for p in (e["start"], e["end"]))}
        assert len(selected) == 4 and selected == geometry, (name, selected, geometry)
        print(json.dumps({"case": f"box {name} interface", "edges": sorted(selected),
                          "independent_geometry": sorted(geometry), "source_face_overlap": sorted(a & b)}), flush=True)


def main():
    stock = named(sr.Box(12, 10, 5), "stock")
    through = named(sr.Cylinder(1, 7, origin=(4, 5, -1)), "bore-through")
    blind = named(sr.Cylinder(1, 4, origin=(4, 5, 3)), "bore-blind")
    square = named(sr.Box(4, 4, 7, origin=(3, 3, -1)), "square-tool")
    check("through cylindrical hole", stock - through, "bore-through", 2, True, [0, 5])
    check("blind cylindrical hole", stock - blind, "bore-blind", 2, True, [3, 5])
    check("square through-hole", stock - square, "square-tool", 8, levels=[0] * 4 + [5] * 4)
    shifted = named(sr.Box(16, 10, 7, origin=(-2, 1, 0)), "stock-shift")
    shifted_tool = named(sr.Cylinder(0.8, 9, origin=(7, 6, -1)), "bore-shift")
    check("resized and shifted stock", shifted - shifted_tool, "bore-shift", 2, True, [0, 7])
    second = named(sr.Cylinder(1, 7, origin=(8, 5, -1)), "bore-second")
    check("first of two holes", (stock - through) - second, "bore-through", 2, True, [0, 5])
    check("second of two holes", (stock - through) - second, "bore-second", 2, True, [0, 5])
    check_split_and_merge()
    check_half_interface_fillet()
    check_pairwise_corner_counterexample()
    check_boolean_operations()


if __name__ == "__main__":
    main()
