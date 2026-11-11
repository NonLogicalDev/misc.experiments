"""Inspection reaches the B-rep and forwards JSONL without corrupting the preview."""

import contextlib
import io
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import solidrecipe as sr
from solidrecipe_runtime import Preview


class InspectTest(unittest.TestCase):
    def test_metadata_stays_on_its_node(self):
        original = sr.Box(10, 8, 6)
        labeled = original.with_metadata(name="stock", role="bracket")
        model = labeled - sr.Cylinder(1, 8, origin=(5, 4, -1)).with_metadata(
            name="hole"
        )
        self.assertNotIn("metadata", original.node)
        self.assertEqual(model.node["left"]["metadata"]["role"], "bracket")
        self.assertEqual(model.node["right"]["metadata"]["name"], "hole")
        with self.assertRaises(TypeError):
            original.with_metadata(value=object())

    def test_jsonl_and_preview_forwarding(self):
        root = Path(__file__).resolve().parents[1]
        cli = root / "target/debug/solidrecipe"
        with TemporaryDirectory() as temp:
            path = Path(temp) / "model.py"
            path.write_text(
                "import solidrecipe as sr\n"
                'model = sr.Box(10, 8, 6).with_metadata(name="stock")\n'
                'sr.inspect(model, name="first")\n'
                'sr.inspect(model, name="second")\n'
            )
            output = Path(temp) / "graph.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "solidrecipe_runtime",
                    "evaluate",
                    str(path),
                    str(output),
                ],
                capture_output=True,
                text=True,
                env={**os.environ, "SOLIDRECIPE_CLI": str(cli)},
                check=True,
            )
            self.assertEqual(result.stdout, "")
            records = [json.loads(line) for line in result.stderr.splitlines()]
            self.assertEqual([r["name"] for r in records], ["first", "second"])
            record = records[0]
            self.assertEqual(record["schema"], "solidrecipe.inspect.v1")
            self.assertEqual(record["indices"], "temporary")
            self.assertEqual(record["graph"]["metadata"]["name"], "stock")
            self.assertEqual(len(record["faces"]), 6)
            self.assertEqual(len(record["edges"]), 12)
            self.assertAlmostEqual(record["volume"], 480.0)
            self.assertEqual(record["bounds"]["min"], [0, 0, 0])
            self.assertEqual(record["bounds"]["max"], [10, 8, 6])
            self.assertEqual(len(record["edges"][0]["adjacent_faces"]), 2)
            preview = Preview(path, cli, temp)
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                preview.rebuild()
            self.assertIsNone(preview.snapshot["error"])
            self.assertEqual(preview.snapshot["revision"], 1)
            self.assertEqual(
                len([json.loads(line) for line in stderr.getvalue().splitlines()]), 2
            )
