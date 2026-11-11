"""Exercise the real Python-to-CLI rebuild and its last-good-result contract."""

import json
import os
import py_compile
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from solidrecipe_runtime import evaluate_source


class PreviewTest(unittest.TestCase):
    def test_evaluation_uses_source_after_same_size_fast_edit(self):
        # An existing pyc with matching size and timestamp must not hide a newer edit.
        with TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "model.py"
            source.write_text("import solidrecipe as sr\nmodel = sr.Box(1, 2, 3)\n")
            timestamp = source.stat().st_mtime_ns
            py_compile.compile(str(source), doraise=True)
            source.write_text("import solidrecipe as sr\nmodel = sr.Box(2, 2, 3)\n")
            os.utime(source, ns=(timestamp, timestamp))
            result = json.loads(evaluate_source(str(source), source.read_text(), "{}"))
            self.assertEqual(result["graph"]["size"][0], 2)


if __name__ == "__main__":
    unittest.main()
