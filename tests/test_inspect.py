"""Inspection reaches the B-rep and forwards JSONL without corrupting the preview."""

import json
import subprocess
import unittest
from pathlib import Path

import solidrecipe as sr


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

    def test_rust_inspection_describes_real_brep(self):
        root = Path(__file__).resolve().parents[1]
        cli = root / "target/debug/solidrecipe"
        shape = sr.Box(10, 8, 6).with_metadata(name="stock")
        result = subprocess.run(
            [str(cli), "inspect-graph"],
            input=json.dumps(shape.node),
            capture_output=True,
            text=True,
            check=True,
        )
        record = json.loads(result.stdout)
        self.assertEqual(record["schema"], "solidrecipe.inspect.v1")
        self.assertEqual(record["indices"], "temporary")
        self.assertEqual(len(record["faces"]), 6)
        self.assertEqual(len(record["edges"]), 12)
        self.assertAlmostEqual(record["volume"], 480.0)
        self.assertEqual(record["bounds"]["min"], [0, 0, 0])
        self.assertEqual(record["bounds"]["max"], [10, 8, 6])
        self.assertEqual(len(record["edges"][0]["adjacent_faces"]), 2)
