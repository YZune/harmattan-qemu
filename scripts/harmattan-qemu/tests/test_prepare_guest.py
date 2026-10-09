import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import platform
import struct
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch, Mock

SPEC = importlib.util.spec_from_file_location('prepare_guest', Path(__file__).resolve().parents[2] / 'prepare-guest.py')
prep = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prep)


class GuestPreparationTests(unittest.TestCase):
    def test_sparse_ranges_reject_overlap_and_oversize(self):
        header = bytearray(0x2000)
        struct.pack_into('<4I', header, 0x40, 0, 4, 3, 2)
        with self.assertRaises(ValueError):
            prep.sparse_ranges(header)
        struct.pack_into('<4I', header, 0x40, 0, 4, 4, 5)
        with self.assertRaises(ValueError):
            prep.sparse_ranges(header, maximum=4096)

    def test_sparse_ranges_reject_empty_or_truncated(self):
        for header in (bytes(0x2000), bytes(8191)):
            with self.assertRaises(ValueError):
                prep.sparse_ranges(header)

    def test_copy_range_preserves_source_and_destination_boundaries(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = Path(tmp) / 'src', Path(tmp) / 'dst'
            src.write_bytes(b'0123456789')
            dst.write_bytes(b'abcdefghij')
            prep.copy_range(src, dst, 2, 3, target_offset=4)
            self.assertEqual(dst.read_bytes(), b'abcd234hij')
            self.assertEqual(src.read_bytes(), b'0123456789')
            with self.assertRaises(ValueError):
                prep.copy_range(src, dst, 9, 2)
            self.assertEqual(dst.read_bytes(), b'abcd234hij')

    def test_extract_slice_refuses_existing_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = Path(tmp) / 'src', Path(tmp) / 'dst'
            src.write_bytes(b'input')
            dst.write_bytes(b'keep')
            with self.assertRaises(ValueError):
                prep.extract_slice(src, dst, {'offset': 0, 'bytes': 5})
            self.assertEqual(dst.read_bytes(), b'keep')

    def test_member_rejects_symlink_and_duplicate_before_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive, output = Path(tmp) / 'input.tar', Path(tmp) / 'output'
            identity = {'member': 'disk', 'bytes': 1}
            for kind in ('symlink', 'duplicate'):
                with tarfile.open(archive, 'w') as tar:
                    m = tarfile.TarInfo('disk')
                    m.size = 1
                    if kind == 'symlink':
                        m.type, m.linkname = tarfile.SYMTYPE, '/outside'
                        tar.addfile(m)
                    else:
                        tar.addfile(m, io.BytesIO(b'x'))
                        tar.addfile(m, io.BytesIO(b'x'))
                with self.assertRaises(ValueError):
                    prep.extract_member(archive, output, identity)
                self.assertFalse(output.exists())

    def test_input_hash_rejects_same_size_substitution(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'input'
            path.write_bytes(b'bad')
            with self.assertRaises(ValueError):
                prep.verify(path, {'bytes': 3, 'sha256': hashlib.sha256(b'yes').hexdigest()})

    def test_invalid_chunk_rejected_before_decompression(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(prep.ctypes, 'CDLL') as library:
            src, stream, root = [Path(tmp) / n for n in ('input', 'stream', 'root')]
            src.write_bytes(struct.pack('<5I', 0xb8c3b410, 0, 1, 65537, 65536))
            with self.assertRaises(ValueError):
                prep.decompress_rootfs(src, stream, root, Path('unused'))
            library.return_value.lzo1x_decompress_safe.assert_not_called()
            self.assertFalse(root.exists())

    def test_debugfs_zero_exit_with_error_is_not_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'edit.log'
            def run(*args, **kwargs):
                kwargs['stdout'].write(b'write: No space left on device\n')
            with patch.object(prep.subprocess, 'run', side_effect=run):
                with self.assertRaises(ValueError):
                    prep.debugfs(Path('debugfs'), Path('image'), ['write src /target'], log, write=True)

    def test_qemu_environment_preserves_macos_framework_requirement(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(prep.platform, 'system', return_value='Darwin'):
            root = Path(tmp)
            qemu = root / 'MacOS/qemu-system-arm'
            with self.assertRaisesRegex(ValueError, 'complete prebuilt application'):
                prep.qemu_environment(qemu)
            frameworks = root / 'Frameworks'
            frameworks.mkdir()
            (frameworks / 'libEGL.1.dylib').touch()
            env = prep.qemu_environment(qemu)
            self.assertEqual(env['DYLD_LIBRARY_PATH'], str(frameworks))
            self.assertEqual(env['HARMATTAN_DGLES_RUNTIME_DIR'], str(frameworks))

    def test_linux_qemu_environment_needs_no_macos_frameworks(self):
        with patch.object(prep.platform, 'system', return_value='Linux'), \
                patch.object(prep.platform, 'machine', return_value='x86_64'), \
                patch.dict(os.environ, {'PATH': '/usr/bin', 'LD_LIBRARY_PATH': '/toolchain/lib',
                                       'HARMATTAN_TEST': 'discard', 'N00_TEST': 'discard',
                                       'DYLD_LIBRARY_PATH': 'discard', 'PYTHONPATH': 'discard'}, clear=True):
            self.assertEqual(prep.qemu_environment(Path('/unused/qemu-system-arm')),
                             {'PATH': '/usr/bin', 'LD_LIBRARY_PATH': '/toolchain/lib'})

    def test_unsupported_host_rejected(self):
        for system, machine in [('Linux', 'aarch64'), ('Windows', 'AMD64')]:
            with self.subTest(system=system, machine=machine), \
                    patch.object(prep.platform, 'system', return_value=system), \
                    patch.object(prep.platform, 'machine', return_value=machine):
                with self.assertRaisesRegex(ValueError, 'macOS or Linux x86_64'):
                    prep.preparation_host()

    def test_macos_clone_keeps_apfs_command(self):
        with patch.object(prep.platform, 'system', return_value='Darwin'), \
                patch.object(prep.subprocess, 'run') as run:
            prep.clone_rootfs(Path('/source'), Path('/target'))
            run.assert_called_once_with(['/bin/cp', '-c', '/source', '/target'], check=True)

    @unittest.skipUnless(platform.system() == 'Linux' and platform.machine() == 'x86_64',
                         'requires Linux x86_64 GNU cp')
    def test_linux_clone_preserves_sparse_holes_and_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp) / 'source', Path(tmp) / 'target'
            with source.open('wb') as output:
                output.write(b'original')
                output.seek(64 * 1024**2 - 4)
                output.write(b'end\n')
            original_hash = prep.sha(source)
            prep.clone_rootfs(source, target)
            self.assertEqual(target.stat().st_size, source.stat().st_size)
            self.assertLess(target.stat().st_blocks * 512, target.stat().st_size // 4)
            self.assertEqual(prep.sha(target), original_hash)
            with target.open('r+b') as output:
                output.write(b'changed!')
            self.assertEqual(prep.sha(source), original_hash)

    def run_mock_boot(self, work, chunks, *, exit_code=0, forced_kill=False, already_exited=False):
        process = Mock()
        process.returncode = exit_code if already_exited else None
        process.poll.side_effect = lambda: process.returncode

        def wait(timeout=None):
            if forced_kill and timeout is not None:
                raise subprocess.TimeoutExpired('qemu-system-arm', timeout)
            process.returncode = exit_code
            return exit_code

        process.wait.side_effect = wait
        with patch.object(prep, 'qemu_environment', return_value={}), \
                patch.object(prep.subprocess, 'Popen', return_value=process) as popen, \
                patch.object(prep.select, 'select', return_value=([process.stdout], [], [])), \
                patch.object(prep.os, 'read', side_effect=[*chunks, b'']):
            try:
                prep.prepare_boot(Path('/qemu-system-arm'), work / 'guest.raw', work / 'kernel', work)
            finally:
                process.stdout.close.assert_called_once()
                self.assertEqual(popen.call_args.kwargs['cwd'], work)
                args = popen.call_args.args[0]
                self.assertEqual(args[args.index('-drive') + 1], 'if=sd,format=raw,file=guest.raw')
                if not already_exited:
                    process.terminate.assert_called_once()
                self.assertEqual(process.kill.called, forced_kill)

    def test_completion_requires_clean_qemu_exit_without_force_kill(self):
        cases = [(0, False, False), (23, False, True), (-15, False, True),
                 (-9, True, True), (0, True, True)]
        for exit_code, forced_kill, rejected in cases:
            with self.subTest(exit_code=exit_code, forced_kill=forced_kill), \
                    tempfile.TemporaryDirectory(prefix='prepare, test-') as tmp:
                work = Path(tmp)
                chunks = [b'boot log\nHARMATTAN_PREPARE_', b'COMPLETE\r\n']
                if rejected:
                    with self.assertRaisesRegex(ValueError, 'did not exit cleanly'):
                        self.run_mock_boot(work, chunks, exit_code=exit_code, forced_kill=forced_kill)
                else:
                    self.run_mock_boot(work, chunks)
                self.assertEqual(json.loads((work / 'prepare-exit.json').read_text()),
                                 {'qemu_exit': exit_code, 'forced_kill': forced_kill})
                self.assertEqual((work / 'prepare-serial.log').read_bytes(), b''.join(chunks))

    def test_clean_exit_without_completion_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            with self.assertRaisesRegex(ValueError, 'did not finish'):
                self.run_mock_boot(work, [b'boot stopped\n'], already_exited=True)
            self.assertEqual(json.loads((work / 'prepare-exit.json').read_text()),
                             {'qemu_exit': 0, 'forced_kill': False})

    def test_kernel_panic_with_completion_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            with self.assertRaisesRegex(ValueError, 'kernel panic'):
                self.run_mock_boot(work, [b'\nHARMATTAN_PREPARE_COMPLETE\nKernel panic\n'])
            self.assertEqual(json.loads((work / 'prepare-exit.json').read_text())['qemu_exit'], 0)

    def test_linux_main_uses_private_stage_beside_output(self):
        with tempfile.TemporaryDirectory(prefix='prepare, test-') as tmp:
            root = Path(tmp)
            tool = root / 'tool'
            tool.write_bytes(b'input or tool')
            tool.chmod(0o755)
            output = root / 'new parent' / 'prepared'
            argv = ['prepare-guest.py']
            for option in ('sdk-exe', 'firmware', 'sevenzip', 'debugfs', 'lzo-library', 'qemu-img', 'qemu-system-arm'):
                argv.extend(['--' + option, str(tool)])
            argv.extend(['--output', str(output)])

            def prepare(args, work):
                self.assertEqual(work.parent, output.parent)
                self.assertEqual(work.stat().st_mode & 0o777, 0o700)
                self.assertFalse(output.exists())
                (work / 'result').write_text('complete')

            with patch('sys.argv', argv), patch.object(prep, 'verify') as verify, \
                    patch.object(prep.platform, 'system', return_value='Linux'), \
                    patch.object(prep.platform, 'machine', return_value='x86_64'), \
                    patch.object(prep, 'prepare', side_effect=prepare):
                prep.main()
            self.assertEqual(verify.call_count, 2)
            self.assertEqual((output / 'result').read_text(), 'complete')
            self.assertEqual(list(output.parent.iterdir()), [output])
            self.assertEqual(tool.read_bytes(), b'input or tool')

    def test_existing_output_refused_before_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'existing'
            output.mkdir()
            argv = ['prepare-guest.py']
            for option in ('sdk-exe', 'firmware', 'sevenzip', 'debugfs', 'lzo-library', 'qemu-img', 'qemu-system-arm'):
                argv.extend(['--' + option, str(Path(tmp) / 'unused')])
            argv.extend(['--output', str(output)])
            with patch('sys.argv', argv), patch.object(prep, 'verify') as verify:
                with self.assertRaises(ValueError):
                    prep.main()
                verify.assert_not_called()
            self.assertEqual(list(output.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
