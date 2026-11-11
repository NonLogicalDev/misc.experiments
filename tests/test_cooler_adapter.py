"""Exercise the adapter example through the actual graph-to-mesh CLI."""

import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from solidrecipe_runtime import evaluate_model


class CoolerAdapterTest(unittest.TestCase):
    def test_default_adapter_builds(self):
        root = Path(__file__).resolve().parents[1]
        with TemporaryDirectory() as temp:
            graph = Path(temp) / "graph.json"
            mesh = Path(temp) / "adapter.obj"
            evaluate_model(root / "examples/cooler_adapter.py", graph)
            result = subprocess.run(
                [str(root / "target/debug/solidrecipe"), str(graph), str(mesh)],
                check=True,
                capture_output=True,
                text=True,
            )
            stats = json.loads(result.stdout)
            # The volume and nonempty mesh catch dropped cuts or a failed graph build.
            self.assertAlmostEqual(stats["volume"], 8192.1658, delta=0.1)
            self.assertGreater(stats["triangles"], 0)
            self.assertTrue(mesh.read_text().startswith("v "))
