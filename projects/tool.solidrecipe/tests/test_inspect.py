"""Inspection reaches the B-rep and forwards JSONL without corrupting the preview."""

import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

import solidrecipe as sr


class InspectTest(unittest.TestCase):
    def test_blend_graph_accepts_one_edge_selection_method(self):
        identity = {"feature": "stock", "kind": "edge", "roles": ["x_min", "y_min"]}
        shape = sr.Box(2, 3, 4)
        for blend in (
            lambda **selection: shape.fillet(radius=0.2, **selection),
            lambda **selection: shape.chamfer(distance=0.2, **selection),
        ):
            with self.subTest(blend=blend):
                model = blend(edge_refs=[identity])
                self.assertEqual(model.node["edge_identities"], [identity])
                self.assertNotIn("points", model.node)
                self.assertNotIn("tolerance", model.node)
                points = [[0, 0, 2]]
                point_model = blend(edge_points=points)
                self.assertEqual(point_model.node["points"], points)
                self.assertEqual(point_model.node["tolerance"], 0.01)
                self.assertNotIn("edge_identities", point_model.node)
                for selection in (
                    {},
                    {"edge_refs": []},
                    {"edge_refs": [{"kind": "face"}]},
                    {"edge_refs": [identity], "edge_points": points},
                ):
                    with self.assertRaises(ValueError):
                        blend(**selection)
                # The identity is a snapshot, not an alias to caller-owned data.
                identity["roles"][0] = "changed"
                self.assertEqual(model.node["edge_identities"][0]["roles"][0], "x_min")
                identity["roles"][0] = "x_min"

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
            self.assertEqual(shape.face_ref("z_max"), face_id)
            self.assertEqual(shape.edge_between_faces("y_min", "x_min"), edge_id)
            self.assertEqual(shape.resolve(face_id)["area"], 6)
        with inspect_with([], []):
            with self.assertRaisesRegex(ValueError, "unknown or unavailable"):
                shape.resolve(face_id)
            with self.assertRaisesRegex(
                ValueError, "missing or identity is unavailable"
            ):
                shape.edge_between_faces("x_min", "y_min")
        with patch.object(
            sr,
            "_inspect_graph",
            return_value=json.dumps(
                {"faces": [], "edges": [], "tracked_identities": [face_id]}
            ),
        ):
            with self.assertRaisesRegex(ValueError, "no surviving tracked descendant"):
                shape.resolve(face_id)
        with inspect_with([{"identity": face_id}, {"identity": face_id}], []):
            with self.assertRaisesRegex(ValueError, "split or ambiguous"):
                shape.resolve(face_id)
            with self.assertRaisesRegex(ValueError, "ambiguous or split"):
                shape.face_ref("z_max")
        with inspect_with([{"identities": [face_id, other_id]}], []):
            with self.assertRaisesRegex(ValueError, "merged"):
                shape.resolve(face_id)
            with self.assertRaisesRegex(ValueError, "merged"):
                shape.face("z_max")
        # A merge with an unnamed origin still has only one reported identity.
        with inspect_with([{"identity": face_id, "merged": True}], []):
            with self.assertRaisesRegex(ValueError, "merged"):
                shape.resolve(face_id)
            with self.assertRaisesRegex(ValueError, "merged"):
                shape.face_ref("z_max")

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

    def test_reference_selected_blends_reach_the_kernel(self):
        root = Path(__file__).resolve().parents[1]
        cli = root / "target/debug/solidrecipe"
        stock = sr.Box(10, 8, 6).with_metadata(id="stock")

        def inspect_graph(shape):
            return subprocess.run(
                [str(cli), "inspect-graph"],
                input=json.dumps(shape.node),
                capture_output=True,
                text=True,
            )

        initial = inspect_graph(stock)
        self.assertEqual(initial.returncode, 0, initial.stderr)
        original = json.loads(initial.stdout)
        identity = next(
            edge["identity"]
            for edge in original["edges"]
            if edge["identity"]["roles"] == ["x_min", "y_min"]
        )
        for shape in (
            stock.fillet(edge_refs=[identity], radius=0.5),
            stock.chamfer(edge_refs=[identity], distance=0.5),
        ):
            with self.subTest(kind=shape.node["kind"]):
                result = inspect_graph(shape)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertLess(json.loads(result.stdout)["volume"], original["volume"])

        missing = {**identity, "feature": "missing"}
        result = inspect_graph(stock.fillet(edge_refs=[missing], radius=0.5))
        self.assertNotEqual(result.returncode, 0)

    def test_python_resolution_reports_real_kernel_history(self):
        cli = Path(__file__).resolve().parents[1] / "target/debug/solidrecipe"

        def inspect(graph):
            return subprocess.run(
                [str(cli), "inspect-graph"],
                input=graph,
                capture_output=True,
                text=True,
                check=True,
            ).stdout

        # Use the same bridge contract as the embedded runtime, but exercise real
        # kernel output for each result instead of constructing mock reports.
        with patch.object(sr, "_inspect_graph", side_effect=inspect):
            stock = sr.Box(10, 10, 10).with_metadata(id="stock")
            split_id = stock.edge_between_faces("x_min", "y_min")
            self.assertEqual(stock.face_ref("z_max")["role"], "z_max")
            split = stock - sr.Box(12, 12, 2, origin=(-1, -1, 4))
            with self.assertRaisesRegex(ValueError, "split or ambiguous"):
                split.resolve(split_id)

            removed_id = stock.edge("y_min", "z_min")["identity"]
            removed = stock - sr.Box(12, 12, 6, origin=(-1, -1, -1))
            with self.assertRaisesRegex(ValueError, "no surviving tracked descendant"):
                removed.resolve(removed_id)
            with self.assertRaisesRegex(ValueError, "unknown or unavailable"):
                stock.resolve({**split_id, "feature": "unknown"})

            left = sr.Box(1, 1, 1).with_metadata(id="left")
            joined = left + sr.Box(1, 1, 1, origin=(1, 0, 0))
            merged = next(
                edge
                for edge in sr.inspect_data(joined)["edges"]
                if edge.get("merged") and edge.get("identity")
            )
            with self.assertRaisesRegex(ValueError, "merged"):
                joined.resolve(merged["identity"])

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
