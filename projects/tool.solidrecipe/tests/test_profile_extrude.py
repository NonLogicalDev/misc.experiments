"""Profiles travel through the real graph evaluator into editable B-reps."""

import json
import math
import subprocess
import unittest
from pathlib import Path

import solidrecipe as sr

CLI = Path(__file__).resolve().parents[1] / "target/debug/solidrecipe"


def inspect(shape):
    return subprocess.run(
        [str(CLI), "inspect-graph"],
        input=json.dumps(shape.node),
        text=True,
        capture_output=True,
    )


class ProfileExtrusionTest(unittest.TestCase):
    def test_polygon_with_circular_hole_extrudes_and_booleans(self):
        outline = sr.Polygon([(0, 0), (10, 0), (10, 8), (0, 8)])
        profile = sr.Profile(outline, holes=[sr.Circle((5, 4), 1, clockwise=True)])
        solid = profile.extrude(5)
        result = inspect(solid)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertAlmostEqual(report["volume"], (80 - math.pi) * 5, delta=0.01)
        self.assertEqual(report["identity_status"], "unavailable")
        # A profile is a graph input, not caller-owned mutable segment data.
        outline[0]["a"][0] = 100
        self.assertEqual(solid.node["region"]["outer"]["segs"][0]["a"], [0, 0])
        cut = solid - sr.Box(2, 2, 7, origin=(1, 1, -1))
        cut_result = inspect(cut)
        self.assertEqual(cut_result.returncode, 0, cut_result.stderr)
        self.assertAlmostEqual(
            json.loads(cut_result.stdout)["volume"], (76 - math.pi) * 5, delta=0.01
        )

    def test_explicit_plane_places_and_orients_extrusion(self):
        frame = sr.Plane(origin=(2, 3, 4), x_dir=(0, 1, 0), y_dir=(0, 0, 1))
        solid = sr.Profile(
            sr.Polygon([(0, 0), (4, 0), (4, 3), (0, 3)]), plane=frame
        ).extrude(5)
        result = inspect(solid)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertAlmostEqual(report["volume"], 60, delta=0.001)
        for actual, expected in zip(report["bounds"]["min"], [2, 3, 4], strict=True):
            self.assertAlmostEqual(actual, expected, delta=0.001)
        for actual, expected in zip(report["bounds"]["max"], [7, 7, 7], strict=True):
            self.assertAlmostEqual(actual, expected, delta=0.001)
        sketch = sr.Sketch(sr.Polygon([(0, 0), (4, 0), (4, 3), (0, 3)]), plane=frame)
        sketch_result = inspect(sketch.profile_at((2, 1)).extrude(5))
        self.assertEqual(sketch_result.returncode, 0, sketch_result.stderr)
        self.assertAlmostEqual(
            json.loads(sketch_result.stdout)["volume"], 60, delta=0.001
        )

    def test_connected_cubic_segment_extrudes(self):
        # An arch closed by one line: the cubic is preserved in the graph.
        segments = [
            sr.Line((0, 0), (4, 0)),
            sr.CubicBezier((4, 0), (4, 4), (0, 4), (0, 0)),
        ]
        solid = sr.Profile(segments).extrude(2)
        result = inspect(solid)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertAlmostEqual(json.loads(result.stdout)["volume"], 19.2, delta=0.01)
        self.assertEqual(solid.node["region"]["outer"]["segs"][1]["type"], "cubic")

    def test_fit_point_spline_is_connected_and_extrudes(self):
        points = [(0, 0), (4, 0), (4, 3), (0, 3)]
        loop = sr.CatmullRom(points, closed=True)
        self.assertEqual(len(loop), len(points))
        for index, segment in enumerate(loop):
            self.assertEqual(segment["p0"], list(points[index]))
            self.assertEqual(segment["p3"], loop[(index + 1) % len(loop)]["p0"])
        result = inspect(sr.Profile(loop).extrude(2))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertGreater(json.loads(result.stdout)["volume"], 0)

    def test_invalid_geometry_and_frame_are_rejected(self):
        with self.assertRaises(ValueError):
            sr.Profile(sr.Polygon([(0, 0), (1, 0), (1, 1)])).extrude(0)
        broken = sr.Profile([sr.Line((0, 0), (1, 0))]).extrude(1)
        self.assertNotEqual(inspect(broken).returncode, 0)
        frame = {"origin": [0, 0, 0], "x_dir": [2, 0, 0], "y_dir": [0, 1, 0]}
        invalid = sr.Profile(sr.Polygon([(0, 0), (1, 0), (1, 1)]), plane=frame).extrude(
            1
        )
        self.assertIn("orthonormal", inspect(invalid).stderr)

    def test_crossing_curve_splits_sketch_into_regions(self):
        curves = sr.Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        curves.append(sr.Line((0, 5), (10, 5)))
        sketch = sr.Sketch(curves)
        for point in [(5, 2), (5, 8)]:
            result = inspect(sketch.profile_at(point).extrude(2))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertAlmostEqual(json.loads(result.stdout)["volume"], 100, delta=0.01)
        self.assertNotEqual(inspect(sketch.profile_at((5, 5)).extrude(2)).returncode, 0)
        self.assertNotEqual(
            inspect(sketch.profile_at((15, 5)).extrude(2)).returncode, 0
        )

    def test_nested_circles_select_disk_and_annulus(self):
        sketch = sr.Sketch(sr.Circle((0, 0), 4) + sr.Circle((0, 0), 2))
        for point, area in [((0, 0), 4 * math.pi), ((3, 0), 12 * math.pi)]:
            result = inspect(sketch.profile_at(point).extrude(2))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertAlmostEqual(
                json.loads(result.stdout)["volume"], area * 2, delta=0.02
            )

    def test_offset_circle_creates_selectable_annulus(self):
        circle = sr.Circle((0, 0), 4)
        sketch = sr.Sketch(circle).offset(circle, 1)
        result = inspect(sketch.profile_at((3.5, 0)).extrude(2))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertAlmostEqual(
            json.loads(result.stdout)["volume"], 14 * math.pi, delta=0.02
        )
        self.assertEqual(sketch._data["offsets"][0]["distance"], 1)

    def test_offset_line_participates_in_regions(self):
        curves = sr.Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        divider = sr.Line((0, 5), (10, 5))
        sketch = sr.Sketch([*curves, divider]).offset([divider], 2)
        result = inspect(sketch.profile_at((5, 6)).extrude(2))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertAlmostEqual(json.loads(result.stdout)["volume"], 40, delta=0.01)

    def test_offset_closed_polygon_and_invalid_sources(self):
        polygon = sr.Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        sketch = sr.Sketch(polygon).offset(polygon, 1)
        result = inspect(sketch.profile_at((0.5, 5)).extrude(2))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertAlmostEqual(json.loads(result.stdout)["volume"], 72, delta=0.01)
        with self.assertRaises(ValueError):
            sr.Sketch([polygon[0], polygon[0]]).offset([polygon[0]], 1)
        too_large = sr.Sketch(sr.Circle((0, 0), 1)).offset(sr.Circle((0, 0), 1), 2)
        self.assertNotEqual(
            inspect(too_large.profile_at((0, 0)).extrude(1)).returncode, 0
        )

    def test_sketch_cubic_region(self):
        curves = [
            sr.Line((0, 0), (4, 0)),
            sr.CubicBezier((4, 0), (4, 4), (0, 4), (0, 0)),
        ]
        result = inspect(sr.Sketch(curves).profile_at((2, 1)).extrude(2))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertAlmostEqual(json.loads(result.stdout)["volume"], 19.2, delta=0.02)

    def test_plane_from_extrusion_direction(self):
        curves = sr.Polygon([(0, 0), (4, 0), (4, 3), (0, 3)])
        for frame in (
            sr.Plane(origin=(2, 3, 4), y_dir=(0, 0, 1), z_dir=(1, 0, 0)),
            sr.Plane(origin=(2, 3, 4), x_dir=(0, 1, 0), z_dir=(1, 0, 0)),
            sr.Plane(origin=(2, 3, 4), x_dir=(0, 1, 0), y_dir=(0, 0, 1)),
        ):
            result = inspect(
                sr.Sketch(curves, plane=frame).profile_at((2, 1)).extrude(5)
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            for actual, expected in zip(
                report["bounds"]["max"], (7, 7, 7), strict=True
            ):
                self.assertAlmostEqual(actual, expected, delta=0.001)
        with self.assertRaises(ValueError):
            sr.Plane(z_dir=(0, 0, 0))
        with self.assertRaises(ValueError):
            sr.Plane(x_dir=(1, 0, 0), y_dir=(1, 0, 0))

    def test_cubic_offset_participates_in_region_search(self):
        curve = sr.CubicBezier((0, 0), (3, 2), (7, 2), (10, 0))
        boundary = [
            sr.Line((0, 0), (0, 3)),
            sr.Line((10, 0), (10, 3)),
            sr.Line((0, 3), (10, 3)),
        ]
        sketch = sr.Sketch([curve, *boundary]).offset([curve], 0.4)
        result = inspect(sketch.profile_at((5, 1.7)).extrude(1))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertGreater(json.loads(result.stdout)["volume"], 4)
        self.assertLess(json.loads(result.stdout)["volume"], 4.5)

    def test_intersecting_circles_select_lens(self):
        sketch = sr.Sketch(sr.Circle((0, 0), 2) + sr.Circle((2, 0), 2))
        result = inspect(sketch.profile_at((1, 0)).extrude(1))
        self.assertEqual(result.returncode, 0, result.stderr)
        expected_area = 8 * math.pi / 3 - 2 * math.sqrt(3)
        self.assertAlmostEqual(
            json.loads(result.stdout)["volume"], expected_area, delta=0.02
        )


if __name__ == "__main__":
    unittest.main()
