"""Capture real B-rep inspection data at adapter stages without editing the model.

Run with the project's Python and an existing debug CLI; JSON is written to stdout.
Snapshot indices identify entities only within their exact evaluated body. The
in-memory source instrumentation retains the original model operations and adds
references to intermediate graph nodes; it is not a query implementation.
"""

import json
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[4]
source_path = root / "examples/cooler_adapter.py"
source = source_path.read_text()
markers = {
    "        if entry_fillets:\n": "        snapshots.append(('before_entry_fillets', shape))\n",
    "        if underside_chamfer:\n": "        snapshots.append(('before_underside_chamfer', shape))\n",
}
for marker, injection in markers.items():
    if source.count(marker) != 1:
        raise RuntimeError(f"Expected exactly one instrumentation marker: {marker!r}")
    source = source.replace(marker, injection + marker)
namespace = {"__name__": "adapter_inspection_probe", "snapshots": []}
exec(compile(source, str(source_path), "exec"), namespace)

results = []
for side, height in (("left", 4.5), ("left", 4.7), ("right", 4.5), ("right", 4.7)):
    namespace["snapshots"].clear()
    namespace["adapter"](side=side, slot_height=height)
    for stage, shape in namespace["snapshots"]:
        process = subprocess.run(
            [str(root / ".work/target/debug/solidrecipe"), "inspect-graph"],
            input=json.dumps(shape.node),
            text=True,
            capture_output=True,
            check=True,
        )
        results.append(
            {
                "side": side,
                "slot_height": height,
                "stage": stage,
                "inspection": json.loads(process.stdout),
            }
        )
print(json.dumps(results, separators=(",", ":")))
