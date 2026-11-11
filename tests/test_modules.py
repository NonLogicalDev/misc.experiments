"""Module namespaces, reusable factories, annotations and load boundaries."""

import json
import os
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

from solidrecipe_runtime import evaluate_source


class ModulesTest(unittest.TestCase):
    def test_modules_and_annotated_factory(self):
        root = Path(__file__).resolve().parents[1]
        hardware = root / "examples/modules/hardware.py"
        result = json.loads(
            evaluate_source(str(hardware), hardware.read_text(), "{}", "mounts.bracket")
        )
        self.assertNotIn("error", result)
        self.assertEqual(result["output"], "mounts.bracket")
        self.assertIn("spacers.round", result["outputs"])
        param = result["parameters"][0]
        self.assertEqual(
            (param["name"], param["unit"], param["minimum"], param["maximum"]),
            ("slot_height", "mm", 4.5, 4.7),
        )
        self.assertEqual(result["graph"]["right"]["size"][2], 4.6)
        changed = json.loads(
            evaluate_source(
                str(hardware),
                hardware.read_text(),
                '{"slot_height": 4.7}',
                "mounts.bracket",
            )
        )
        self.assertEqual(changed["graph"]["right"]["size"][2], 4.7)

    def test_load_is_scoped_and_tracks_file(self):
        root = Path(__file__).resolve().parents[1]
        assembly = root / "examples/modules/assembly.py"
        result = json.loads(evaluate_source(str(assembly), assembly.read_text(), "{}"))
        self.assertNotIn("error", result)
        self.assertEqual(result["outputs"], ["default"])
        self.assertEqual(result["graph"]["right"]["size"][2], 4.5)
        self.assertIn(
            str((assembly.parent / "hardware.py").resolve()), result["sources"]
        )

    def test_function_name_is_default_export_name(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "model.py"
            source = (
                "import solidrecipe as sr\n"
                "def my_bracket(width=3): return sr.Box(width, 2, 1)\n"
                "sr.export(my_bracket)\n"
            )
            result = json.loads(evaluate_source(str(path), source, "{}"))
            self.assertEqual(result["outputs"], ["my_bracket"])
            self.assertEqual(result["parameters"][0]["name"], "width")

    def test_duplicate_and_circular_modules_fail_with_context(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model = root / "model.py"
            source = 'import solidrecipe as sr\nwith sr.module("x"):\n    pass\nwith sr.module("x"):\n    pass\n'
            result = json.loads(evaluate_source(str(model), source, "{}"))
            self.assertIn("duplicate export or module", result["error"])
            model.write_text('import solidrecipe as sr\nsr.load("model.py")\n')
            result = json.loads(evaluate_source(str(model), model.read_text(), "{}"))
            self.assertIn("circular SolidRecipe module load", result["error"])

    def test_live_loaded_file_changes_and_missing_file_recovers(self):
        root = Path(__file__).resolve().parents[1]
        cli = root / "target/debug/solidrecipe"
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            model = path / "model.py"
            library = path / "library.py"
            model.write_text(
                'import solidrecipe as sr\nlib = sr.load("library.py")\nsr.export(lib.mounts.bracket())\n'
            )

            def write_library(width):
                library.write_text(
                    f'import solidrecipe as sr\nwith sr.module("mounts"):\n    def bracket(): return sr.Box({width}, 2, 3)\n    sr.export("bracket", bracket)\n'
                )

            process = subprocess.Popen(
                [str(cli), "serve", str(model), "--port", "0", "--no-browser"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            try:
                process.stdout.readline()
                url = (
                    process.stdout.readline()
                    .strip()
                    .removeprefix("Viewer: ")
                    .rstrip("/")
                )
                self.assertTrue(url.startswith("http://127.0.0.1:"), url)

                def wait_for(predicate):
                    deadline = time.monotonic() + 30
                    while time.monotonic() < deadline:
                        with urlopen(url + "/api/preview", timeout=5) as response:
                            result = json.load(response)
                        if predicate(result):
                            return result
                        time.sleep(0.1)
                    self.fail(f"preview did not reach expected state: {result}")

                wait_for(
                    lambda state: state["error"] and "library.py" in state["error"]
                )
                write_library(10)
                # CRLF must not look like a fresh edit on every watcher poll.
                library.write_bytes(library.read_bytes().replace(b"\n", b"\r\n"))
                first = wait_for(
                    lambda state: state["revision"] == 1 and not state["building"]
                )
                time.sleep(0.7)
                with urlopen(url + "/api/preview", timeout=5) as response:
                    self.assertEqual(json.load(response)["revision"], 1)
                write_library(12)
                changed = wait_for(
                    lambda state: state["revision"] == 2 and not state["building"]
                )
                self.assertNotEqual(first["mesh"], changed["mesh"])
                library.unlink()
                failure = wait_for(
                    lambda state: state["error"] and "library.py" in state["error"]
                )
                self.assertEqual(failure["mesh"], changed["mesh"])
                write_library(11)
                wait_for(lambda state: state["revision"] == 3 and not state["building"])
            finally:
                os.killpg(process.pid, signal.SIGINT)
                process.communicate(timeout=15)

    def test_viewer_selects_annotated_module_and_reuses_geometry(self):
        root = Path(__file__).resolve().parents[1]
        cli = root / "target/debug/solidrecipe"
        with tempfile.TemporaryDirectory() as temp:
            model = Path(temp) / "model.py"
            model.write_text(
                "from typing import Annotated\n"
                "import solidrecipe as sr\n"
                'with sr.module("mounts"):\n'
                "    @sr.exportf\n"
                '    def bracket(height: Annotated[float, sr.Param(minimum=2, maximum=5, unit="mm")] = 3):\n'
                "        return sr.Box(10, 10, 10) - sr.Box(4, 4, height, origin=(2, 2, -1))\n"
                "sr.export(sr.Box(1, 2, 3))\n"
            )
            process = subprocess.Popen(
                [str(cli), "serve", str(model), "--port", "0", "--no-browser"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            try:
                process.stdout.readline()
                url = (
                    process.stdout.readline()
                    .strip()
                    .removeprefix("Viewer: ")
                    .rstrip("/")
                )
                self.assertTrue(url.startswith("http://127.0.0.1:"), url)

                def wait_for(revision):
                    deadline = time.monotonic() + 30
                    while time.monotonic() < deadline:
                        with urlopen(url + "/api/preview", timeout=5) as response:
                            state = json.load(response)
                        if state["error"]:
                            self.fail(state["error"])
                        if state["revision"] >= revision and not state["building"]:
                            return state
                        time.sleep(0.1)
                    self.fail("preview did not finish")

                def post(path, data):
                    request = Request(
                        url + path,
                        data=json.dumps(data).encode(),
                        method="POST",
                        headers={"Content-Type": "application/json", "Origin": url},
                    )
                    with urlopen(request, timeout=5) as response:
                        return json.load(response)

                initial = wait_for(1)
                self.assertEqual(initial["output"], "default")
                self.assertIn("mounts.bracket", initial["outputs"])
                post("/api/output", {"name": "mounts.bracket"})
                bracket = wait_for(2)
                self.assertEqual(bracket["parameters"][0]["unit"], "mm")
                post("/api/parameters", {"values": {"height": 4}})
                changed = wait_for(3)
                self.assertEqual(changed["parameters"][0]["value"], 4)
                self.assertNotEqual(changed["mesh"], bracket["mesh"])
                self.assertGreaterEqual(changed["cache"]["hits"], 1)
                post(
                    "/api/presets",
                    {
                        "name": "tall",
                        "output": "mounts.bracket",
                        "values": {"height": 4},
                    },
                )
                post("/api/output", {"name": "default"})
                self.assertEqual(wait_for(4)["output"], "default")
                with urlopen(url + "/api/presets", timeout=5) as response:
                    saved = json.load(response)["tall"]
                post("/api/parameters", saved)
                restored = wait_for(5)
                self.assertEqual(restored["output"], "mounts.bracket")
                self.assertEqual(restored["parameters"][0]["value"], 4)
            finally:
                os.killpg(process.pid, signal.SIGINT)
                process.communicate(timeout=15)

    def test_embedded_measurements_drive_later_geometry(self):
        root = Path(__file__).resolve().parents[1]
        cli = root / "target/debug/solidrecipe"
        with tempfile.TemporaryDirectory() as temp:
            model = Path(temp) / "model.py"
            model.write_text(
                "import solidrecipe as sr\n"
                'base = sr.Box(2, 3, 4).with_metadata(id="stock")\n'
                'edge = base.edge("x_min", "y_min")\n'
                'assert abs(edge["length"] - 4) < 0.001\n'
                'resized = sr.Box(2, 3, 6).with_metadata(id="stock")\n'
                'assert abs(resized.resolve(edge["identity"])["length"] - 6) < 0.001\n'
                'assert abs(base.face("z_max")["area"] - 6) < 0.001\n'
                "stock = base.scale(2).translate(5, -2, 10)\n"
                'assert abs(stock.resolve(edge["identity"])["length"] - 8) < 0.001\n'
                'assert sr.inspect_data(stock)["identity_status"] == "exact_named_box"\n'
                "measurements = stock.measure()\n"
                "assert measurements.bounds.minimum == (5, -2, 10)\n"
                "assert measurements.bounds.size == (4, 6, 8)\n"
                "assert abs(measurements.volume - 192) < 0.001\n"
                'edges = sr.inspect_data(stock)["edges"]\n'
                "assert len(edges) == 12\n"
                "sr.export(sr.Box(measurements.bounds.size[0], 1, 1, origin=measurements.bounds.maximum))\n"
            )
            process = subprocess.Popen(
                [str(cli), "serve", str(model), "--port", "0", "--no-browser"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            try:
                process.stdout.readline()
                url = (
                    process.stdout.readline()
                    .strip()
                    .removeprefix("Viewer: ")
                    .rstrip("/")
                )
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    with urlopen(url + "/api/preview", timeout=5) as response:
                        state = json.load(response)
                    if state["error"]:
                        self.fail(state["error"])
                    if state["revision"] >= 1:
                        break
                    time.sleep(0.1)
                self.assertGreaterEqual(state["revision"], 1)
                self.assertTrue(state["mesh"])
            finally:
                os.killpg(process.pid, signal.SIGINT)
                process.communicate(timeout=15)
