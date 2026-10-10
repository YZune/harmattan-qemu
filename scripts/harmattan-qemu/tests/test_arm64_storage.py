import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
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
                shutil.copyfile(command[-2], command[-1])
            elif command[1] == 'create':
                (Path(kwargs['cwd']) / 'disk.qcow2').write_bytes(b'initial overlay')
            return subprocess.CompletedProcess(command, 0)
        self.info = {'format': 'qcow2', 'virtual-size': STORAGE.CAPACITY,
                     'backing-filename-format': 'raw',
                     'full-backing-filename': str(self.profile / 'base.raw')}
        self.addCleanup(patch.stopall)
        self.run_disk_tool = run
        self.run = patch.object(STORAGE.subprocess, 'run', side_effect=run).start()
        patch.object(STORAGE.subprocess, 'check_output', side_effect=lambda *a, **k: json.dumps(self.info)).start()
        self.disk_usage = patch.object(STORAGE.shutil, 'disk_usage').start()
        self.disk_usage.return_value.free = 2 * STORAGE.CAPACITY

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

    def test_profile_host_platform_is_explicit_and_cannot_be_reused_across_hosts(self):
        with patch.object(STORAGE.sys, 'platform', 'linux'):
            profile = self.open()
        self.assertEqual(profile.state['host_platform'], 'linux')
        profile.close()
        before = (self.profile / 'profile.json').read_bytes()
        with patch.object(STORAGE.sys, 'platform', 'darwin'):
            with self.assertRaisesRegex(ValueError, 'another host platform'):
                self.open()
        self.assertEqual((self.profile / 'profile.json').read_bytes(), before)

        state = json.loads(before)
        for marker in ('darwin', None):
            if marker is None:
                state.pop('host_platform')
            else:
                state['host_platform'] = marker
            STORAGE.write_json(self.profile / 'profile.json', state)
            with self.subTest(host_platform=marker), patch.object(STORAGE.sys, 'platform', 'linux'):
                with self.assertRaisesRegex(ValueError, 'another host platform'):
                    self.open()
        # Existing unmarked macOS profiles remain compatible on macOS.
        with patch.object(STORAGE.sys, 'platform', 'darwin'):
            self.assertIsNotNone(self.open().fd)

    def test_fresh_copy_failures_never_publish_a_clean_profile(self):
        for failing_source in (self.source, self.profile / 'disk.qcow2'):
            with self.subTest(failing_source=failing_source.name):
                def fail_copy(command, **kwargs):
                    if command[0] == '/bin/cp' and Path(command[-2]) == failing_source:
                        Path(command[-1]).write_bytes(b'partial copy')
                        raise subprocess.CalledProcessError(1, command)
                    return self.run_disk_tool(command, **kwargs)
                self.run.side_effect = fail_copy
                with self.assertRaises(subprocess.CalledProcessError):
                    self.open()
                self.assertFalse((self.profile / 'profile.json').exists())
                self.assertFalse((self.profile / 'checkpoint.qcow2').exists())
                self.assertEqual(list(self.profile.glob('.checkpoint-*')), [])
                self.assertEqual(self.source.read_bytes(), b'untouched source')
                with self.assertRaisesRegex(ValueError, 'not a complete'):
                    self.open()
                shutil.rmtree(self.profile)

    def test_linux_space_failure_never_publishes_a_clean_profile(self):
        with patch.object(STORAGE.sys, 'platform', 'linux'):
            for available in ([0], [2 * STORAGE.CAPACITY, 0]):
                with self.subTest(copy_number=len(available)):
                    self.run.reset_mock()
                    self.disk_usage.side_effect = [SimpleNamespace(free=value) for value in available]
                    with self.assertRaisesRegex(ValueError, 'insufficient free space'):
                        self.open()
                    if len(available) == 1:
                        self.run.assert_not_called()
                        self.assertFalse((self.profile / 'base.raw').exists())
                    self.assertFalse((self.profile / 'profile.json').exists())
                    self.assertFalse((self.profile / 'checkpoint.qcow2').exists())
                    self.assertEqual(list(self.profile.glob('.checkpoint-*')), [])
                    self.assertEqual(self.source.read_bytes(), b'untouched source')
                    shutil.rmtree(self.profile)

    def test_failed_checkpoint_preserves_existing_disk_state_and_checkpoint(self):
        with patch.object(STORAGE.sys, 'platform', 'linux'):
            profile = self.open()
            profile.disk.write_bytes(b'saved user data')
            profile.finish(synced=True, exit_code=0)
            profile.close()
            saved = {name: (self.profile / name).read_bytes() for name in
                     ('profile.json', 'base.raw', 'disk.qcow2', 'checkpoint.qcow2')}

            def fail_copy(command, **kwargs):
                if command[0] == '/bin/cp':
                    Path(command[-1]).write_bytes(b'partial checkpoint')
                    raise subprocess.CalledProcessError(1, command)
                return self.run_disk_tool(command, **kwargs)
            self.run.side_effect = fail_copy
            with self.assertRaises(subprocess.CalledProcessError):
                self.open()
            self.disk_usage.return_value.free = 0
            with self.assertRaisesRegex(ValueError, 'insufficient free space'):
                self.open()
        for name, content in saved.items():
            self.assertEqual((self.profile / name).read_bytes(), content)
        self.assertEqual(list(self.profile.glob('.checkpoint-*')), [])
        self.assertEqual(self.source.read_bytes(), b'untouched source')


class DiskCopyTests(unittest.TestCase):
    def test_platform_copy_commands_and_allocated_space_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / 'source.raw', root / 'copy.raw'
            with source.open('wb') as stream:
                stream.write(b'sparse source')
                stream.truncate(STORAGE.CAPACITY)
            allocated = min(source.stat().st_size, source.stat().st_blocks * 512)
            with patch.object(STORAGE.subprocess, 'run') as run, \
                    patch.object(STORAGE.shutil, 'disk_usage') as usage:
                usage.return_value.free = allocated + STORAGE.COPY_RESERVE
                with patch.object(STORAGE.sys, 'platform', 'darwin'):
                    STORAGE.copy_disk(source, target)
                run.assert_called_once_with(['/bin/cp', '-c', str(source), str(target)], check=True)
                usage.assert_not_called()
                run.reset_mock()
                with patch.object(STORAGE.sys, 'platform', 'linux'):
                    STORAGE.copy_disk(source, target)
                    run.assert_called_once_with(['/bin/cp', '--reflink=auto', '--sparse=always', '--',
                                                 str(source), str(target)], check=True)
                    run.reset_mock()
                    usage.return_value.free -= 1
                    with self.assertRaisesRegex(ValueError, 'insufficient free space'):
                        STORAGE.copy_disk(source, target)
                    run.assert_not_called()
                with patch.object(STORAGE.sys, 'platform', 'unsupported'):
                    with self.assertRaisesRegex(ValueError, 'macOS or Linux'):
                        STORAGE.copy_disk(source, target)

    @unittest.skipUnless(sys.platform == 'linux', 'real GNU sparse copy requires Linux')
    def test_real_linux_sparse_copy_preserves_content_and_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, target = root / 'source.raw', root / 'copy.raw'
            with source.open('wb') as stream:
                stream.write(b'base start')
                stream.seek(4 * 1024 ** 2)
                stream.write(b'base middle')
                stream.truncate(8 * 1024 ** 2)
            original = source.read_bytes()
            source.chmod(0o400)
            STORAGE.copy_disk(source, target)
            self.assertEqual(target.read_bytes(), original)
            self.assertLess(target.stat().st_blocks * 512, target.stat().st_size // 4)
            target.chmod(0o600)
            with target.open('r+b') as stream:
                stream.write(b'edited')
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(source.stat().st_mode & 0o777, 0o400)

    @unittest.skipUnless(sys.platform == 'linux' and hasattr(os, 'memfd_create'),
                         'cross-filesystem fallback requires Linux memfd')
    def test_real_linux_copy_falls_back_when_reflinking_is_unsupported(self):
        # memfd is a sparse tmpfs file: copying to the host temporary directory
        # crosses filesystems, so --reflink=auto must perform a real data copy.
        fd = os.memfd_create('harmattan-sparse-copy-test')
        self.addCleanup(os.close, fd)
        os.write(fd, b'base start')
        os.lseek(fd, 4 * 1024 ** 2, os.SEEK_SET)
        os.write(fd, b'base middle')
        os.ftruncate(fd, 8 * 1024 ** 2)
        source = Path(f'/proc/{os.getpid()}/fd/{fd}')
        original = source.read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'copy.raw'
            self.assertNotEqual(source.stat().st_dev, target.parent.stat().st_dev)
            probe = subprocess.run(['/bin/cp', '--reflink=always', '--', str(source), str(target)],
                                   stderr=subprocess.PIPE)
            self.assertNotEqual(probe.returncode, 0, 'cross-filesystem reflink unexpectedly succeeded')
            target.unlink(missing_ok=True)
            STORAGE.copy_disk(source, target)
            self.assertEqual(target.read_bytes(), original)
            self.assertLess(target.stat().st_blocks * 512, target.stat().st_size // 4)
            with target.open('r+b') as stream:
                stream.write(b'edited')
            self.assertEqual(source.read_bytes(), original)


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
