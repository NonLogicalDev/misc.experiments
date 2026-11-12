"""Test actual source-face capture for the adapter's setback edge.

The adapter source is instrumented in memory to give its input boxes stable IDs.
The existing `face_ref` API captures those primitive faces. The incidence query
is experimental Python over real inspect-graph output, not a production API.
"""

import json
import runpy
import subprocess
from pathlib import Path

import solidrecipe as sr

ROOT = Path(__file__).resolve().parents[4]
helpers = runpy.run_path(str(ROOT / "docs/plans/_owner/artifacts/test-construction-queries.py"))


def inspect_json(graph):
    return subprocess.run([str(ROOT / "target/debug/solidrecipe"), "inspect-graph"],
                          input=graph, text=True, capture_output=True, check=True).stdout


def main():
    # Same bridge contract as the embedded runtime; no production runtime is altered.
    old = sr._inspect_graph
    sr._inspect_graph = inspect_json
    try:
        ns = helpers["instrument"]()
        for side in ("left", "right"):
            base = sr.Box(12.5, 71, 8.5).with_metadata(id="base")
            setback_x = -0.1 if side == "left" else 11.5
            setback = sr.Box(1.1, 71.2, 7.5 - 4.6,
                             origin=(setback_x, -0.1, -0.1)).with_metadata(id="setback")
            base_face = base.face_ref("z_min")
            setback_face = setback.face_ref("x_max" if side == "left" else "x_min")

            ns["snapshots"].clear()
            ns["adapter"](side=side, slot_height=4.6)
            body = next(shape for stage, shape in ns["snapshots"] if stage == "chamfer")
            report = helpers["inspect"](body)
            descendants = lambda ref: {f["index"] for f in report["faces"]
                                       if ref in f.get("identities", [])}
            edges = helpers["between"](report, descendants(base_face), descendants(setback_face))
            expected = {46} if side == "left" else {47}
            assert edges == expected, (side, edges, expected)
            print(json.dumps({"side": side, "base_face_ref": base_face,
                              "setback_face_ref": setback_face,
                              "matching_pre_chamfer_edges": sorted(edges)}), flush=True)
    finally:
        sr._inspect_graph = old


if __name__ == "__main__":
    main()
