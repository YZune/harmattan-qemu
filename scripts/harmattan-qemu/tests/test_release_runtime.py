"""Prepared-input safety and precompiled helper behavior without historical media."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runtime = load('release_runtime', SCRIPTS.parent / 'release/runtime.py')
helpers = load('release_helpers', SCRIPTS / 'prebuilt-helpers.py')
packager = load('release_packager', SCRIPTS.parent / 'release/package-macos.py')


class DeploymentTargetTests(unittest.TestCase):
    def test_linker_tool_version_is_not_a_macos_requirement(self):
        commands = '''Load command 12
              cmd LC_BUILD_VERSION
          cmdsize 32
         platform 1
            minos 14.0
              sdk 26.4
           ntools 1
             tool 3
          version 1267.0
        '''
        self.assertEqual(packager.minimum_macos(commands), (14, 0))

    def test_legacy_deployment_command_is_supported(self):
        self.assertEqual(packager.minimum_macos('''Load command 1
              cmd LC_VERSION_MIN_MACOSX
          cmdsize 16
          version 10.15
              sdk 11.0
        '''), (10, 15))


class ReleaseInputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.state = self.base / 'state'
        self.kernel = self.base / 'kernel'
        self.kernel.write_bytes(b'synthetic kernel')
        self.pin = patch.object(runtime, 'KERNEL_SHA256', runtime.digest(self.kernel))
        self.pin.start()
        self.addCleanup(self.pin.stop)
        self.disk = self.base / 'disk.raw'
        data = bytearray(8192)
        data[510:512] = b'\x55\xaa'
        data[466] = 0x83
        struct.pack_into('<II', data, 470, 2, 14)
        data[2104:2106] = b'\x53\xef'
        self.disk.write_bytes(data)

    def import_disk(self, replace=False):
        def clone(command, **kwargs):
            self.assertEqual(command[:2], ['/bin/cp', '-c'])
            shutil.copyfile(command[2], command[3])
        with patch.object(runtime.subprocess, 'run', side_effect=clone), contextlib.redirect_stdout(io.StringIO()):
            runtime.import_inputs(self.state, self.kernel, self.disk, replace)

    def test_import_retains_original_and_records_private_copy(self):
        original = self.disk.read_bytes()
        self.import_disk()
        kernel, disk = runtime.check(self.state)
        self.assertEqual(disk.read_bytes(), original)
        self.assertNotEqual(disk, self.disk)
        self.assertEqual(kernel.read_bytes(), self.kernel.read_bytes())
        self.assertEqual(self.disk.read_bytes(), original)

    def test_wrong_kernel_fails_before_creating_state(self):
        self.kernel.write_bytes(b'wrong')
        with self.assertRaisesRegex(ValueError, 'kernel SHA'):
            self.import_disk()
        self.assertFalse(self.state.exists())

    def test_rejects_firmware_without_partition_table(self):
        self.disk.write_bytes(b'firmware' * 1024)
        with self.assertRaisesRegex(ValueError, 'MBR'):
            runtime.inspect_disk(self.disk)

    def test_partition_extent_and_ext_signature_are_required(self):
        with self.disk.open('r+b') as stream:
            stream.seek(474)
            stream.write(struct.pack('<I', 200))
        with self.assertRaisesRegex(ValueError, 'root partition'):
            runtime.inspect_disk(self.disk)
        with self.disk.open('r+b') as stream:
            stream.seek(474)
            stream.write(struct.pack('<I', 14))
            stream.seek(2104)
            stream.write(b'XX')
        with self.assertRaisesRegex(ValueError, 'ext filesystem'):
            runtime.inspect_disk(self.disk)

    def test_changed_imported_disk_requires_reimport(self):
        self.import_disk()
        _, disk = runtime.check(self.state)
        with disk.open('ab') as stream: stream.write(b'changed')
        with self.assertRaisesRegex(ValueError, 'disk changed'):
            runtime.check(self.state)

    def test_existing_profile_is_preserved_even_when_replaced(self):
        self.import_disk()
        first = runtime.check(self.state)
        with self.assertRaisesRegex(ValueError, 'already configured'):
            self.import_disk()
        self.import_disk(replace=True)
        self.assertTrue(all(p.is_file() for p in first))
        self.assertNotEqual(runtime.check(self.state), first)

    def test_clone_failure_leaves_configuration_unmodified(self):
        self.import_disk()
        settings = (self.state / 'inputs.json').read_bytes()
        with patch.object(runtime.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'cp')):
            with self.assertRaises(subprocess.CalledProcessError):
                runtime.import_inputs(self.state, self.kernel, self.disk, replace=True)
        self.assertEqual((self.state / 'inputs.json').read_bytes(), settings)


class PrebuiltHelperTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / helpers.HELPERS['orientation'][0]
        self.path.parent.mkdir()
        data = bytearray(52)
        data[:7] = b'\x7fELF\x01\x01\x01'
        data[16:20] = b'\x02\x00\x28\x00'
        self.path.write_bytes(data)
        self.record = {'sha256': runtime.digest(self.path), 'sources': {
            'orientation-provider-guest.c': runtime.digest(SCRIPTS / 'orientation-provider-guest.c')}}
        self.save()

    def save(self):
        (self.root / 'helpers.json').write_text(json.dumps({'schema_version': 1, 'helpers': {'orientation': self.record}}))

    def test_prebuilt_builder_never_looks_for_compiler_or_debugfs(self):
        env = {**os.environ, 'HARMATTAN_PREBUILT_HELPERS': str(self.root),
               'HARMATTAN_PYTHON': sys.executable, 'HARMATTAN_ARMEL_CLANG': '/nonexistent/clang',
               'HARMATTAN_DEBUGFS': '/nonexistent/debugfs', 'PATH': '/usr/bin:/bin'}
        subprocess.run(['/bin/sh', str(SCRIPTS / 'build-orientation-guest.sh')], env=env, check=True)

    def test_corrupt_binary_and_changed_source_fail_closed(self):
        self.path.write_bytes(self.path.read_bytes() + b'corrupt')
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            helpers.verify(self.root, 'orientation')
        self.record['sha256'] = runtime.digest(self.path)
        self.record['sources']['orientation-provider-guest.c'] = '0' * 64
        self.save()
        with self.assertRaisesRegex(ValueError, 'source mismatch'):
            helpers.verify(self.root, 'orientation')

    def test_wrong_elf_is_rejected(self):
        self.path.write_bytes(b'not an ARM helper')
        with self.assertRaisesRegex(ValueError, 'ELF'):
            helpers.verify(self.root, 'orientation')

    def test_source_traversal_is_rejected(self):
        self.record['sources'] = {'../outside.c': '0' * 64}
        self.save()
        with self.assertRaisesRegex(ValueError, 'filename'):
            helpers.verify(self.root, 'orientation')


if __name__ == '__main__':
    unittest.main()
