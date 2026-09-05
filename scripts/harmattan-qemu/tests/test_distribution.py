"""Publication importer safety checks using only tiny synthetic input files."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    'input_importer', Path(__file__).resolve().parents[2] / 'import-local-inputs.py')
IMPORTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(IMPORTER)


class DistributionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.src = self.base / 'source'
        self.dst = self.base / 'destination'
        self.relative = Path('downloads/tools/test-input.txt')
        (self.src / self.relative).parent.mkdir(parents=True)
        (self.src / self.relative).write_bytes(b'synthetic input')
        (self.dst / 'docs').mkdir(parents=True)
        self.item = {'path': str(self.relative), 'sha256': hashlib.sha256(b'synthetic input').hexdigest()}
        self.save_manifest()

    def save_manifest(self):
        (self.dst / 'docs/inputs.json').write_text(json.dumps({'inputs': [self.item]}))

    def invoke(self, apply=False):
        argv = ['import-local-inputs.py', str(self.src)] + (['--apply'] if apply else [])
        with patch.object(IMPORTER, 'ROOT', self.dst), patch('sys.argv', argv), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            IMPORTER.main()

    def test_dry_run_does_not_create_destination(self):
        self.invoke()
        self.assertFalse((self.dst / 'downloads').exists())

    def test_success_copies_only_allowlisted_input(self):
        (self.src / 'private.log').write_text('not part of the manifest')
        self.invoke(True)
        self.assertEqual((self.dst / self.relative).read_bytes(), b'synthetic input')
        self.assertFalse((self.dst / 'private.log').exists())

    def test_hash_mismatch_leaves_destination_unmodified(self):
        (self.src / self.relative).write_bytes(b'wrong input')
        with self.assertRaises(SystemExit):
            self.invoke(True)
        self.assertFalse((self.dst / 'downloads').exists())

    def test_existing_destination_is_preserved(self):
        (self.dst / self.relative).parent.mkdir(parents=True)
        (self.dst / self.relative).write_bytes(b'keep me')
        with self.assertRaises(SystemExit):
            self.invoke(True)
        self.assertEqual((self.dst / self.relative).read_bytes(), b'keep me')


if __name__ == '__main__':
    unittest.main()
