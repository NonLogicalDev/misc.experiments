"""Run the B-rep vertex probe using existing Rust libraries; remove its binary.

The linked rlibs are selected by modification time from the existing target.
They must be built from the intended source revision; this script does not build
the project or certify that the libraries match the current checkout.
"""

import json
import runpy
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
ARTIFACTS = ROOT / "docs/plans/_owner/artifacts"
DEPS = ROOT / ".work/target/debug/deps"


def newest(pattern):
    paths = list(DEPS.glob(pattern))
    if not paths:
        raise RuntimeError(f"Missing existing Rust build artifact: {pattern}")
    return max(paths, key=lambda p: p.stat().st_mtime)


def main():
    ns = runpy.run_path(str(ARTIFACTS / "test-construction-queries.py"))["instrument"]()
    inputs = []
    for side, height in (("left", 4.5), ("left", 4.6), ("left", 4.7), ("right", 4.5), ("right", 4.7)):
        ns["snapshots"].clear()
        ns["adapter"](side=side, slot_height=height)
        shape = next(shape for stage, shape in ns["snapshots"] if stage == "final")
        corner = [3, 10.85, 8.5] if side == "left" else [9.5, 10.8, 8.5]
        inputs.append({"case": f"{side}-{height}", "graph": shape.node, "corner": corner})
    with tempfile.TemporaryDirectory(prefix="solidrecipe-vertex-probe-") as temp:
        binary = str(Path(temp) / "probe")
        subprocess.run(["rustc", "--edition=2021", str(ARTIFACTS / "verify-adapter-vertices.rs"),
                        "-L", f"dependency={DEPS}", "--extern", f"solidrecipe_core={newest('libsolidrecipe_core-*.rlib')}",
                        "--extern", f"serde_json={newest('libserde_json-*.rlib')}", "-o", binary], check=True)
        proc = subprocess.run([binary], input="".join(json.dumps(i) + "\n" for i in inputs),
                              capture_output=True, text=True, check=True)
    for line in proc.stdout.splitlines():
        result = json.loads(line)
        assert len(result["incidences"]) == 1, result
        edges = result["incidences"][0]["edges"]
        assert len(edges) == 3, result
        if result["case"] == "left-4.6":
            assert set(edges) == {35, 36, 43}, result
            assert set(result["incidences"][0]["faces"]) == {10, 12, 13}, result
        print(json.dumps(result))
    assert len(proc.stdout.splitlines()) == len(inputs)


if __name__ == "__main__":
    main()
