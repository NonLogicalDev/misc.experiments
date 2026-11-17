"""Test source-and-incidence selection while editing a two-hole model.

The proposed query is implemented only in this harness, over real inspect-graph
results. A geometric oracle is used for test verification, not for selection.
"""

import json
import math
import subprocess
from pathlib import Path

import solidrecipe as sr

ROOT = Path(__file__).resolve().parents[4]


def inspect(shape):
    p = subprocess.run([str(ROOT / ".work/target/debug/solidrecipe"), "inspect-graph"],
                       input=json.dumps(shape.node), text=True, capture_output=True, check=True)
    return json.loads(p.stdout)


def faces_from(report, feature, role):
    return {f["index"] for f in report["faces"] if any(
        i.get("feature") == feature and i.get("role") == role for i in f.get("identities", []))}


def rims(report, feature):
    wall = faces_from(report, feature, "side")
    other = {f["index"] for f in report["faces"]} - wall
    return {e["index"] for e in report["edges"] if any(
        a != b and a in wall and b in other for a in e["adjacent_faces"] for b in e["adjacent_faces"])}


def oracle(report, x, y, radius, levels):
    def near(a, b):
        return math.isclose(a, b, rel_tol=0, abs_tol=1e-6)
    out = set()
    for e in report["edges"]:
        c = e["curve"]
        if c["kind"] != "circle":
            continue
        o = c["frame"]["origin"]
        if near(o[0], x) and near(o[1], y) and near(c["radius"], radius) and any(near(o[2], z) for z in levels):
            out.add(e["index"])
    return out


def construct(a, b, radius, *, reverse=False, offset=(0, 0, 0)):
    stock = sr.Box(12, 10, 5).with_metadata(id="stock")
    holes = {name: sr.Cylinder(radius, 7, origin=(x, 5, -1)).with_metadata(id=name)
             for name, x in (("hole-A", a), ("hole-B", b))}
    result = stock
    for name in (("hole-B", "hole-A") if reverse else ("hole-A", "hole-B")):
        result -= holes[name]
    return result.translate(*offset) if offset != (0, 0, 0) else result


def test_variant(name, a, b, radius, reverse=False, offset=(0, 0, 0)):
    report = inspect(construct(a, b, radius, reverse=reverse, offset=offset))
    result = {}
    for feature, x in (("hole-A", a), ("hole-B", b)):
        got = rims(report, feature)
        expected = oracle(report, x + offset[0], 5 + offset[1], radius,
                          [offset[2], offset[2] + 5])
        assert len(got) == 2 and got == expected, (name, feature, got, expected)
        result[feature] = sorted(got)
    assert not (set(result["hole-A"]) & set(result["hole-B"]))
    print(json.dumps({"case": name, "selected": result,
                      "parameters": {"A_x": a, "B_x": b, "radius": radius,
                                     "reverse_cuts": reverse, "translation": offset}}), flush=True)


def deletion():
    stock = sr.Box(12, 10, 5).with_metadata(id="stock")
    small = sr.Cylinder(0.8, 7, origin=(4, 5, -1)).with_metadata(id="small")
    larger = sr.Cylinder(1.5, 7, origin=(4, 5, -1)).with_metadata(id="larger")
    report = inspect((stock - small) - larger)
    source_exists = any(i.get("feature") == "small" for i in report["tracked_identities"])
    surviving = faces_from(report, "small", "side")
    assert source_exists and not surviving, (source_exists, surviving)
    print(json.dumps({"case": "larger cut removes earlier wall", "small_source_recorded": source_exists,
                      "small_wall_descendants": sorted(surviving),
                      "caveat": "current empty identity result does not distinguish deletion from lost history"}), flush=True)


def main():
    test_variant("baseline", 3, 9, 0.8)
    test_variant("reverse independent cuts", 3, 9, 0.8, reverse=True)
    test_variant("move holes and change radius", 2, 10, 0.5)
    test_variant("exchange named hole positions", 9, 3, 0.8)
    test_variant("translate finished part", 3, 9, 0.8, offset=(20, -4, 3))
    deletion()


if __name__ == "__main__":
    main()
