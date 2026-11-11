"""Verify declarations, live updates and file-backed presets through the CLI."""

import json
import os
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import solidrecipe as sr


class ParametersTest(unittest.TestCase):
    def test_declarations_validate_values_and_metadata(self):
        sr._begin_parameters({"width": 4.5, "enabled": True})
        self.assertEqual(
            sr.parameter("width", 3.0, minimum=1, maximum=5, step=0.1, unit="mm"), 4.5
        )
        self.assertTrue(sr.parameter("enabled", False))
        self.assertEqual(sr._parameter_definitions()[0]["unit"], "mm")
        with self.assertRaises(ValueError):
            sr.parameter("width", 2)
        sr._begin_parameters({"width": 10})
        with self.assertRaises(ValueError):
            sr.parameter("width", 3, maximum=5)

    def test_viewer_updates_and_recalls_presets(self):
        root = Path(__file__).resolve().parents[1]
        cli = root / "target/debug/solidrecipe"
        with tempfile.TemporaryDirectory() as temp:
            model = Path(temp) / "model.py"
            model.write_text(
                "import solidrecipe as sr\n"
                'width = sr.parameter("width", 2.0, minimum=1, maximum=5, step=0.1, unit="mm")\n'
                "model = sr.Box(width, 3, 4)\n"
            )

            def start():
                process = subprocess.Popen(
                    [str(cli), "serve", str(model), "--port", "0", "--no-browser"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    start_new_session=True,
                    env={**os.environ, "UV_CACHE_DIR": "/tmp/solidrecipe-uv-cache"},
                )
                process.stdout.readline()
                url = (
                    process.stdout.readline()
                    .strip()
                    .removeprefix("Viewer: ")
                    .rstrip("/")
                )
                self.assertTrue(url.startswith("http://127.0.0.1:"), url)
                return process, url

            def get(url, path):
                with urlopen(url + path, timeout=5) as response:
                    return json.load(response)

            def post(url, path, value, origin=None):
                request = Request(
                    url + path,
                    data=json.dumps(value).encode(),
                    method="POST",
                    headers={
                        "Content-Type": "application/json",
                        "Origin": origin or url,
                    },
                )
                with urlopen(request, timeout=5) as response:
                    return json.load(response)

            def ready(url, revision):
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    result = get(url, "/api/preview")
                    if result["revision"] >= revision and not result["building"]:
                        return result
                    if result["error"]:
                        self.fail(result["error"])
                    time.sleep(0.1)
                self.fail("preview did not finish")

            def stop(process):
                os.killpg(process.pid, signal.SIGINT)
                process.communicate(timeout=15)

            process, url = start()
            try:
                initial = ready(url, 1)
                self.assertEqual(initial["parameters"][0]["value"], 2.0)
                with self.assertRaises(HTTPError) as error:
                    post(
                        url,
                        "/api/presets",
                        {"name": "bad", "values": {}},
                        "https://example.com",
                    )
                self.assertEqual(error.exception.code, 403)
                error.exception.close()
                values = {"width": 4.0}
                post(url, "/api/parameters", {"values": values})
                updated = ready(url, 2)
                self.assertEqual(updated["parameters"][0]["value"], 4.0)
                self.assertNotEqual(initial["mesh"], updated["mesh"])
                # An invalid edit keeps the last good geometry and can be corrected.
                post(url, "/api/parameters", {"values": {"width": 9}})
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    failed = get(url, "/api/preview")
                    if failed["error"]:
                        break
                    time.sleep(0.1)
                self.assertIn("invalid value", failed["error"])
                self.assertEqual(failed["mesh"], updated["mesh"])
                post(url, "/api/parameters", {"values": values})
                self.assertEqual(ready(url, 3)["parameters"][0]["value"], 4.0)
                post(url, "/api/presets", {"name": "wide", "values": values})
                self.assertEqual(
                    json.loads(model.with_name("model.py.presets.json").read_text())[
                        "wide"
                    ],
                    values,
                )
            finally:
                stop(process)
            process, url = start()
            try:
                ready(url, 1)
                saved = get(url, "/api/presets")["wide"]
                post(url, "/api/parameters", {"values": saved})
                self.assertEqual(ready(url, 2)["parameters"][0]["value"], 4.0)
            finally:
                stop(process)
