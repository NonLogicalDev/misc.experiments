"""Exercise the real Python-to-CLI rebuild and its last-good-result contract."""

import json
import os
import py_compile
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from solidrecipe_runtime import Preview, evaluate_model


class PreviewTest(unittest.TestCase):
    def test_evaluation_uses_source_after_same_size_fast_edit(self):
        # An existing pyc with matching size and timestamp must not hide a newer edit.
        with TemporaryDirectory() as temp:
            root = Path(temp)
            source, graph = root / "model.py", root / "graph.json"
            source.write_text("from solidrecipe import Box\nmodel = Box(1, 2, 3)\n")
            timestamp = source.stat().st_mtime_ns
            py_compile.compile(str(source), doraise=True)
            source.write_text("from solidrecipe import Box\nmodel = Box(2, 2, 3)\n")
            os.utime(source, ns=(timestamp, timestamp))
            evaluate_model(source, graph)
            self.assertEqual(json.loads(graph.read_text())["size"][0], 2)

    def test_rebuild_retains_previous_mesh_on_error_and_recovers(self):
        cli = Path(__file__).resolve().parents[1] / "target/debug/solidrecipe"
        with TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "model.py"
            preview = Preview(source, cli, root)
            source.write_text("from solidrecipe import Box\nmodel = Box(1, 2, 3)\n")
            preview.rebuild()
            self.assertIsNone(preview.snapshot["error"])
            first_mesh = preview.snapshot["mesh"]
            self.assertTrue(first_mesh)
            self.assertEqual(preview.snapshot["revision"], 1)

            # A failed edit must not replace the last usable preview with a partial result.
            source.write_text('raise ValueError("broken model")\n')
            preview.rebuild()
            self.assertIn("broken model", preview.snapshot["error"])
            self.assertEqual(preview.snapshot["revision"], 1)
            self.assertEqual(preview.snapshot["mesh"], first_mesh)

            source.write_text("from solidrecipe import Box\nmodel = Box(2, 2, 3)\n")
            preview.rebuild()
            self.assertIsNone(preview.snapshot["error"])
            self.assertEqual(preview.snapshot["revision"], 2)
            self.assertNotEqual(preview.snapshot["mesh"], first_mesh)


if __name__ == "__main__":
    unittest.main()
