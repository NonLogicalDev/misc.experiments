"""Inspection reaches the B-rep and forwards JSONL without corrupting the preview."""

import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

import solidrecipe as sr


class InspectTest(unittest.TestCase):
    def test_instance_graph_preserves_occurrence_and_shared_nodes(self):
        stock = sr.Box(2, 3, 4).with_metadata(id="stock")
        shared = stock.translate(5, 0, 0) + stock.scale(2)
        graph = json.loads(json.dumps(shared.node))
        self.assertEqual(
            graph["left"]["body"]["occurrence"],
            graph["right"]["body"]["occurrence"],
        )

        other = sr.Box(2, 3, 4).with_metadata(id="stock")
        self.assertNotEqual(stock.node["occurrence"], other.node["occurrence"])
        instance = stock.instance("left")
        self.assertEqual(instance.node["kind"], "instance")
        self.assertEqual(instance.node["name"], "left")
        self.assertEqual(instance.node["body"]["occurrence"], stock.node["occurrence"])
        self.assertNotEqual(instance.node["occurrence"], stock.node["occurrence"])
        for bad_name in ("", "  ", None, 3):
            with self.subTest(name=bad_name), self.assertRaises(ValueError):
                stock.instance(bad_name)

    def test_reference_lookup_rejects_missing_split_and_merged_results(self):
        face_id = {"feature": "stock", "kind": "face", "role": "z_max"}
        other_id = {"feature": "tool", "kind": "face", "role": "z_max"}
        edge_id = {
            "feature": "stock",
            "kind": "edge",
            "roles": ["x_min", "y_min"],
        }
        shape = sr.Box(2, 3, 4)

        def inspect_with(faces, edges):
            return patch.object(
                sr,
                "_inspect_graph",
                return_value=json.dumps({"faces": faces, "edges": edges}),
            )

        # Null identities occur on transformed generated entities; skip them.
        with inspect_with(
            [{"identity": None}, {"identities": [face_id], "area": 6}],
            [{"identity": None}, {"identities": [edge_id], "length": 4}],
        ):
            self.assertEqual(shape.face("z_max")["area"], 6)
            self.assertEqual(shape.edge("y_min", "x_min")["length"], 4)
            self.assertEqual(shape.resolve(face_id)["area"], 6)
        with inspect_with([], []):
            with self.assertRaisesRegex(
                ValueError, "missing or identity is unavailable"
            ):
                shape.resolve(face_id)
        with inspect_with([{"identity": face_id}, {"identity": face_id}], []):
            with self.assertRaisesRegex(ValueError, "split or ambiguous"):
                shape.resolve(face_id)
        with inspect_with([{"identities": [face_id, other_id]}], []):
            with self.assertRaisesRegex(ValueError, "merged"):
                shape.resolve(face_id)
            with self.assertRaisesRegex(ValueError, "merged"):
                shape.face("z_max")

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
