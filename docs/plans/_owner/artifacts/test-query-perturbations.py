"""Change the adapter after the selection and compare two query intentions.

This uses actual B-rep provenance and edge-face uses, but is not a production
query evaluator. The original model source is instrumented only in memory.
"""

import json
import runpy
from pathlib import Path

import solidrecipe as sr

ROOT = Path(__file__).resolve().parents[4]
helpers = runpy.run_path(str(ROOT / "docs/plans/_owner/artifacts/test-construction-queries.py"))
instrument, inspect, source, between, edges_of = (helpers[name] for name in
    ("instrument", "inspect", "from_source", "between", "edges_of"))


def main():
    ns = instrument()
    ns["adapter"](side="left", slot_height=4.6)
    body = next(shape for stage, shape in ns["snapshots"] if stage == "final")
    # Intersect the slot's back wall halfway along its length with a later bore.
    bore = sr.Cylinder(0.5, 20, origin=(9, 30, -1)).with_metadata(id="later-bore")
    report = inspect(body - bore)
    back = source(report, "groove", "x_max")
    floor = source(report, "groove", "z_min")
    roof = source(report, "groove", "z_max")
    ends = source(report, "groove", "y_min") | source(report, "groove", "y_max")
    except_floor = edges_of(report, back) - between(report, back, floor)
    named_sides = between(report, back, roof) | between(report, back, ends)
    print(json.dumps({"back_faces": sorted(back), "boundary_except_floor": sorted(except_floor),
                      "named_roof_and_ends": sorted(named_sides),
                      "extra_from_bore": sorted(except_floor - named_sides),
                      "unknown_faces": [f["index"] for f in report["faces"]
                                        if f.get("origin_status") == "generated or untracked"]}), flush=True)
    assert len(named_sides) == 4, named_sides  # The new bore splits the original top edge.
    assert named_sides < except_floor, (named_sides, except_floor)


if __name__ == "__main__":
    main()
