import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('build_trainer', Path(__file__).with_name('build_trainer.py'))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

class ResumeTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); (self.root/'spirv').mkdir(); self.dest=self.root/'spirv/test.spv'; self.journal=self.root/'completion.jsonl'; self.compiler=Path('/compiler'); self.cmd=[str(self.compiler),'shader','-o',str(self.dest)]; self.context='a'*64
    def record(self, content=b'\x03\x02\x23\x07valid', **changes):
        self.dest.write_bytes(content); row={'command':self.cmd,'destination':str(self.dest),'context_sha256':self.context,'output_sha256':hashlib.sha256(content).hexdigest()};row.update(changes)
        with self.journal.open('a') as f:f.write(json.dumps(row)+'\n')
    def read(self):return m.read_completions(self.journal,self.compiler,self.root,self.context)
    def test_missing_legacy_and_incomplete_output_never_resume(self):
        self.assertEqual(self.read(),{});self.record(); self.dest.write_bytes(b'\x03\x02\x23\x07partial');self.assertEqual(self.read(),{})
        self.journal.write_text(json.dumps({'command':self.cmd,'output_sha256':'0'*64})+'\n');self.assertEqual(self.read(),{})
    def test_hash_magic_and_latest_retry(self):
        self.record();self.assertEqual(self.read()['test.spv'],self.cmd)
        self.dest.write_bytes(b'\x03\x02\x23\x07changed');self.assertEqual(self.read(),{})
        self.record(b'\x03\x02\x23\x07retry');self.assertEqual(self.read()['test.spv'],self.cmd)
        self.record(b'not spirv');self.assertEqual(self.read(),{})
    def test_truncated_malformed_and_wrong_destination_fail_closed(self):
        self.record();self.journal.write_text(self.journal.read_text()+'{"command":');
        with self.assertRaises(ValueError):self.read()
        self.journal.write_text('not json\n');
        with self.assertRaises(ValueError):self.read()
        self.journal.unlink();self.record(destination=str(self.root/'elsewhere'))
        with self.assertRaises(ValueError):self.read()
    def test_context_matches_and_changed_or_unbound_recompile(self):
        self.record();self.assertEqual(self.read()['test.spv'],self.cmd)
        self.context='b'*64;self.assertEqual(self.read(),{})
        self.journal.unlink();self.record(context_sha256=None);self.assertEqual(self.read(),{})
    def test_context_is_persisted_before_use(self):
        first=m.write_context(self.root,{'commit':'one'});self.assertEqual(first,m.digest(self.root/'build-context.json'))
        self.assertNotEqual(first,m.write_context(self.root,{'commit':'two'}))

    def test_different_command_is_not_equal_to_requested(self):
        other=self.cmd+['-Ddifferent'];self.record(command=other);self.assertNotEqual(self.read()['test.spv'],self.cmd)

if __name__=='__main__':unittest.main()
