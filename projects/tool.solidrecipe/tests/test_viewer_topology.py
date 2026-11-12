"""Exercise viewer selections through the real preview HTTP server.

Topology indices belong to one server session and successful build revision. A
rejected request or failed build must not change the current selected geometry.
"""

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


class ViewerTopologyTest(unittest.TestCase):
    def test_highlights_follow_the_exact_preview_revision(self):
        root = Path(__file__).resolve().parents[1]
        cli = root / "target/debug/solidrecipe"
        with tempfile.TemporaryDirectory() as temp:
            model = Path(temp) / "model.py"
            model.write_text(
                "import solidrecipe as sr\n"
                'width = sr.parameter("width", 2.0, minimum=1, maximum=5)\n'
                "model = sr.Box(width, 3, 4)\n"
            )
            # Capture stderr in a task-owned temporary file, so an error cannot
            # block the server by filling a pipe; both resources are closed below.
            with tempfile.TemporaryFile(mode="w+") as diagnostics:
                process = subprocess.Popen(
                    [str(cli), "serve", str(model), "--port", "0", "--no-browser"],
                    stdout=subprocess.PIPE,
                    stderr=diagnostics,
                    text=True,
                    start_new_session=True,
                    env={**os.environ, "UV_CACHE_DIR": str(Path(temp) / "uv-cache")},
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

                    def get():
                        with urlopen(url + "/api/preview", timeout=5) as response:
                            return json.load(response)

                    def post(path, value):
                        request = Request(
                            url + path,
                            data=json.dumps(value).encode(),
                            method="POST",
                            headers={"Content-Type": "application/json", "Origin": url},
                        )
                        with urlopen(request, timeout=5) as response:
                            return json.load(response)

                    def wait_for(predicate):
                        deadline = time.monotonic() + 30
                        while time.monotonic() < deadline:
                            result = get()
                            if predicate(result):
                                return result
                            time.sleep(0.1)
                        self.fail("preview did not reach the requested state")

                    initial = wait_for(
                        lambda state: state["revision"] == 1 and not state["building"]
                    )
                    self.assertIsNone(initial["selection_error"])
                    self.assertEqual(len(initial["inspection"]["faces"]), 6)
                    self.assertEqual(len(initial["inspection"]["edges"]), 12)
                    self.assertEqual(len(initial["topology"]["faces"]), 6)
                    self.assertEqual(len(initial["topology"]["edges"]), 12)
                    self.assertTrue(initial["topology"]["faces"][0]["triangles"])
                    for face, inspected in zip(
                        initial["topology"]["faces"],
                        initial["inspection"]["faces"],
                        strict=True,
                    ):
                        self.assertEqual(face["index"], inspected["index"])
                        self.assertEqual(len(face["edge_ids"]), len(face["triangles"]))
                        self.assertEqual(
                            len(face["segment_ids"]), len(face["triangles"])
                        )
                        for ids, segments in zip(
                            face["edge_ids"], face["segment_ids"], strict=True
                        ):
                            self.assertEqual(len(ids), 3)
                            self.assertEqual(len(segments), 3)
                            for edge, segment in zip(ids, segments, strict=True):
                                if edge is not None:
                                    self.assertTrue(face["boundary_complete"])
                                    self.assertIn(edge, inspected["edges"])
                                    self.assertIsNotNone(segment)
                                    self.assertLess(
                                        segment + 1,
                                        len(
                                            initial["topology"]["edges"][edge]["points"]
                                        ),
                                    )
                                else:
                                    self.assertIsNone(segment)
                    self.assertGreaterEqual(
                        len(initial["topology"]["edges"][0]["points"]), 2
                    )
                    selection = {
                        "session": initial["session"],
                        "revision": 1,
                        "faces": [0],
                        "edges": [0],
                    }
                    post("/api/highlights", selection)
                    selected = get()
                    self.assertEqual(
                        selected["highlights"]["faces"],
                        [initial["topology"]["faces"][0]],
                    )
                    self.assertEqual(
                        selected["highlights"]["edges"],
                        [initial["topology"]["edges"][0]],
                    )
                    self.assertGreater(
                        selected["selection_revision"], initial["selection_revision"]
                    )

                    # Stale sessions, stale revisions and a partly invalid request
                    # must all leave the previous selection completely unchanged.
                    for change in (
                        {"session": "other"},
                        {"revision": 0},
                        {"faces": [1], "edges": [99]},
                    ):
                        with (
                            self.subTest(change=change),
                            self.assertRaises(HTTPError) as error,
                        ):
                            post("/api/highlights", {**selection, **change})
                        self.assertEqual(error.exception.code, 400)
                        error.exception.close()
                        after_rejection = get()
                        self.assertEqual(
                            after_rejection["highlights"], selected["highlights"]
                        )
                        self.assertEqual(
                            after_rejection["selection_revision"],
                            selected["selection_revision"],
                        )

                    # An invalid model edit leaves the last-good result selected.
                    post("/api/parameters", {"values": {"width": 9}})
                    failed = wait_for(lambda state: bool(state["error"]))
                    self.assertEqual(failed["revision"], 1)
                    self.assertEqual(failed["highlights"], selected["highlights"])

                    post("/api/parameters", {"values": {"width": 4}})
                    rebuilt = wait_for(
                        lambda state: state["revision"] == 2 and not state["building"]
                    )
                    self.assertEqual(rebuilt["highlights"], {"faces": [], "edges": []})
                    self.assertGreater(
                        rebuilt["selection_revision"], selected["selection_revision"]
                    )
                    with self.assertRaises(HTTPError) as error:
                        post("/api/highlights", selection)
                    self.assertEqual(error.exception.code, 400)
                    error.exception.close()
                finally:
                    os.killpg(process.pid, signal.SIGINT)
                    process.communicate(timeout=15)


if __name__ == "__main__":
    unittest.main()
