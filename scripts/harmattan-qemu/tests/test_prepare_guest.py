import hashlib
import importlib.util
import io
from pathlib import Path
import struct
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
