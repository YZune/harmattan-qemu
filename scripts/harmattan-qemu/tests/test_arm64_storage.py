import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location('storage', ROOT / 'scripts/harmattan-qemu/arm64-storage.py')
STORAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STORAGE)


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'source.raw'
        self.source.write_bytes(b'untouched source')
        self.profile = self.root / 'profile'
        # Source-only tests stub disk tools; file ownership, locking, state and
        # subprocess descriptor inheritance use real operating-system behavior.
        def run(command, **kwargs):
            if command[0] == '/bin/cp':
                shutil.copyfile(command[2], command[3])
            elif command[1] == 'create':
                (Path(kwargs['cwd']) / 'disk.qcow2').write_bytes(b'initial overlay')
            return subprocess.CompletedProcess(command, 0)
        self.info = {'format': 'qcow2', 'virtual-size': STORAGE.CAPACITY,
                     'backing-filename-format': 'raw',
                     'full-backing-filename': str(self.profile / 'base.raw')}
        self.addCleanup(patch.stopall)
        patch.object(STORAGE.subprocess, 'run', side_effect=run).start()
        patch.object(STORAGE.subprocess, 'check_output', side_effect=lambda *a, **k: json.dumps(self.info)).start()

    def open(self):
        profile = STORAGE.Profile(self.profile, self.source, 'test-qemu-img')
        self.addCleanup(profile.close)
        return profile

    def test_reject_unrecognized_directory_without_overwriting(self):
        self.profile.mkdir()
        sentinel = self.profile / 'valuable-file'
        sentinel.write_bytes(b'keep')
        with self.assertRaisesRegex(ValueError, 'not a complete'):
            self.open()
        self.assertEqual(sentinel.read_bytes(), b'keep')
        self.assertEqual(list(self.profile.iterdir()), [sentinel])

    def test_exclusive_lock_survives_controller_close_in_inherited_child(self):
        profile = self.open()
        child = subprocess.Popen([sys.executable, '-c', 'import sys; sys.stdin.buffer.read(1)'],
                                 stdin=subprocess.PIPE, pass_fds=(profile.fd,))
        try:
            profile.close()
            with self.assertRaisesRegex(ValueError, 'already open'):
                self.open()
        finally:
            child.communicate(b'x', timeout=10)
        self.assertIsNotNone(self.open().fd)

    def test_clean_commit_and_unclean_checkpoint_are_distinct(self):
        profile = self.open()
        checkpoint = self.profile / 'checkpoint.qcow2'
        self.assertEqual(checkpoint.read_bytes(), b'initial overlay')
        profile.disk.write_bytes(b'new saved data')
        with self.assertRaises(ValueError):
            profile.finish(synced=False, exit_code=0)
        with self.assertRaises(ValueError):
            profile.finish(synced=True, exit_code=1)
        profile.close()
        profile = self.open()
        self.assertEqual(checkpoint.read_bytes(), b'initial overlay')
        self.assertEqual(profile.disk.read_bytes(), b'new saved data')
        profile.finish(synced=True, exit_code=0)
        profile.close()
        self.assertEqual(self.open().state['sessions'], 3)
        self.assertEqual(checkpoint.read_bytes(), b'new saved data')
        self.assertEqual(self.source.read_bytes(), b'untouched source')
        self.assertEqual((self.profile / 'base.raw').stat().st_mode & 0o222, 0)

    def test_reject_external_backing_and_mutable_base(self):
        profile = self.open()
        self.info['full-backing-filename'] = str(self.source)
        with self.assertRaisesRegex(ValueError, 'own fixed raw'):
            profile.validate()
        self.info['full-backing-filename'] = str(profile.base)
        profile.base.chmod(0o600)
        with self.assertRaisesRegex(ValueError, 'read-only'):
            profile.validate()

    def test_reject_symlinks_in_existing_profile(self):
        profile = self.open()
        profile.close()
        profile.disk.unlink()
        profile.disk.symlink_to(self.source)
        with self.assertRaisesRegex(ValueError, 'non-regular'):
            self.open()
        self.assertEqual(self.source.read_bytes(), b'untouched source')


class StorageProtocolTests(unittest.TestCase):
    def test_only_the_owned_single_drive_loses_snapshot(self):
        original = ['qemu-system-arm', '-drive', 'if=sd,format=qcow2,file=/run/image', '-snapshot', '-display', 'none']
        result = STORAGE.persistent_command(original, Path('/profile with spaces,a/disk.qcow2'))
        self.assertIn('-snapshot', original)
        self.assertNotIn('-snapshot', result)
        self.assertEqual(result[2], 'if=sd,format=qcow2,file=/profile with spaces,,a/disk.qcow2')
        for bad in (original[:-3] + original[-2:], original + ['-snapshot'],
                    original + ['-drive', 'if=sd,file=other'], ['qemu', '-snapshot', '-drive']):
            with self.assertRaises(ValueError):
                STORAGE.persistent_command(bad, Path('/profile/disk.qcow2'))

    def test_shutdown_request_must_be_complete_and_regular(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'request'
            self.assertFalse(STORAGE.shutdown_requested(path))
            path.write_bytes(b's')
            self.assertFalse(STORAGE.shutdown_requested(path))
            path.write_bytes(b'sync\n')
            self.assertTrue(STORAGE.shutdown_requested(path))
            path.write_bytes(b'sync\nextra')
            with self.assertRaises(ValueError):
                STORAGE.shutdown_requested(path)
            path.unlink()
            target = Path(directory) / 'other'
            target.write_bytes(b'sync\n')
            path.symlink_to(target)
            with self.assertRaises(ValueError):
                STORAGE.shutdown_requested(path)

    def test_native_request_preserves_existing_files(self):
        compiler = shutil.which('cc')
        if not compiler:
            self.skipTest('native C compiler unavailable')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'test.c'
            source.write_text('#include "n00-storage-shutdown.h"\nint main(void) { return n00_storage_shutdown_request() + 1; }\n')
            binary = root / 'test'
            subprocess.run([compiler, '-Wall', '-Wextra', '-Werror', '-I', str(ROOT / 'ports/qemu-n00'),
                            str(source), '-o', str(binary)], check=True)
            env = os.environ.copy()
            env.pop('N00_COCOA_STORAGE_SHUTDOWN', None)
            self.assertEqual(subprocess.run([binary], env=env).returncode, 1)
            target = root / 'request'
            env['N00_COCOA_STORAGE_SHUTDOWN'] = str(target)
            self.assertEqual(subprocess.run([binary], env=env).returncode, 2)
            self.assertEqual(target.read_bytes(), b'sync\n')
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            target.write_bytes(b'keep')
            self.assertEqual(subprocess.run([binary], env=env, stderr=subprocess.PIPE).returncode, 0)
            self.assertEqual(target.read_bytes(), b'keep')


if __name__ == '__main__':
    unittest.main()
