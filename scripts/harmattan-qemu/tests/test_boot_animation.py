import importlib.util
import io
from pathlib import Path
import platform
import stat
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('boot', SCRIPTS / 'arm64-boot-animation.py')
BOOT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BOOT)


def filesystem():
    """Synthetic ext4 metadata and ordinary text, never a firmware fixture."""
    data = bytearray(32 * 4096)
    struct.pack_into('<II', data, 1024, 16, 32)
    struct.pack_into('<I', data, 1024 + 24, 2)
    struct.pack_into('<I', data, 1024 + 40, 16)
    data[1024 + 56:1024 + 58] = b'\x53\xef'
    struct.pack_into('<H', data, 1024 + 88, 256)
    struct.pack_into('<I', data, 1024 + 96, 0x242)
    struct.pack_into('<I', data, 4096 + 8, 2)
    names = BOOT.MOVIE.strip('/').split('/')
    for index in range(len(names) + 1):
        number, block = 2 + index, 4 + index
        inode = 2 * 4096 + (number - 1) * 256
        directory = index < len(names)
        struct.pack_into('<H', data, inode, (stat.S_IFDIR if directory else stat.S_IFREG) | 0o755)
        struct.pack_into('<I', data, inode + 4, 4096 if directory else 7)
        if index == 0:  # The retail root uses direct blocks.
            struct.pack_into('<I', data, inode + 40, block)
        else:
            struct.pack_into('<I', data, inode + 32, 0x80000)
            struct.pack_into('<HHHHI', data, inode + 40, 0xf30a, 1, 4, 0, 0)
            struct.pack_into('<IHHI', data, inode + 52, 0, 1, 0, block)
        if directory:
            name = names[index].encode()
            struct.pack_into('<IHBB', data, block * 4096, number + 1, 4096, len(name), 2)
            data[block * 4096 + 8:block * 4096 + 8 + len(name)] = name
        else:
            data[block * 4096:block * 4096 + 7] = b'fixture'
    return data


def reader(data):
    return BOOT.Ext4(io.BytesIO(data), 0, len(data))


class BootResourceTests(unittest.TestCase):
    def test_remux_retains_synthetic_packets_and_requires_the_pinned_clip(self):
        def chunk(tag, data):
            return tag + struct.pack('<I', len(data)) + data + bytes(len(data) % 2)
        packets = [b'x' * 45 + b'\x00\x00\x01\xb3' + b'fixture'] + [b'frame' + bytes([i]) for i in range(99)]
        movi = chunk(b'LIST', b'movi' + b''.join(chunk(b'00dc', data) for data in packets))
        idx = chunk(b'idx1', b''.join(struct.pack('<4sIII', b'00dc', 16 if i == 0 else 0, 0, len(data))
                                     for i, data in enumerate(packets)))
        avi = chunk(b'RIFF', b'AVI ' + movi + idx)
        with self.assertRaisesRegex(ValueError, 'unverified'):
            BOOT.remux_movie(avi)
        with patch.object(BOOT, 'MOVIE_SHA256', BOOT.hashlib.sha256(avi).hexdigest()):
            mp4 = BOOT.remux_movie(avi)
        ftyp_length = struct.unpack_from('>I', mp4)[0]
        self.assertEqual(mp4[4:8], b'ftyp')
        mdat_length = struct.unpack_from('>I', mp4, ftyp_length)[0]
        self.assertEqual(mp4[ftyp_length + 4:ftyp_length + 8], b'mdat')
        self.assertEqual(mp4[ftyp_length + 8:ftyp_length + mdat_length], b''.join(packets))
        self.assertEqual(mp4[ftyp_length + mdat_length + 4:ftyp_length + mdat_length + 8], b'moov')
        self.assertIn(b'stss' + struct.pack('>III', 0, 1, 1), mp4)

    def test_remux_rejects_incomplete_riff_even_with_a_test_hash(self):
        avi = b'RIFF' + struct.pack('<I', 12) + b'AVI ' + b'LIST' + struct.pack('<I', 100)
        with patch.object(BOOT, 'MOVIE_SHA256', BOOT.hashlib.sha256(avi).hexdigest()):
            with self.assertRaisesRegex(ValueError, 'exceeds'):
                BOOT.remux_movie(avi)

    def test_direct_root_and_extent_directories(self):
        self.assertEqual(reader(filesystem()).file(BOOT.MOVIE), b'fixture')

    def test_rejects_unsupported_geometry_and_features(self):
        for offset, value in ((24, 31), (40, 0), (96, 0x2c2), (4, 0xffffffff)):
            data = filesystem()
            struct.pack_into('<I', data, 1024 + offset, value)
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                reader(data)

    def test_rejects_symlinks_bad_directory_entries_and_reads_outside_partition(self):
        for mutation in ('symlink', 'entry', 'block', 'huge'):
            data = filesystem()
            inode = 2 * 4096 + 2 * 256  # /usr
            if mutation == 'symlink':
                struct.pack_into('<H', data, inode, stat.S_IFLNK | 0o777)
            elif mutation == 'entry':
                struct.pack_into('<H', data, 4 * 4096 + 4, 0)
            elif mutation == 'block':
                struct.pack_into('<I', data, inode + 60, 32)
            else:
                struct.pack_into('<I', data, inode + 4, BOOT.MAX_FILE + 1)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                reader(data).file(BOOT.MOVIE)

    def test_extent_index_and_cycles(self):
        data = filesystem()
        inode = 2 * 4096 + 2 * 256
        leaf = bytes(data[inode + 40:inode + 100])
        data[20 * 4096:20 * 4096 + 60] = leaf
        struct.pack_into('<H', data, inode + 46, 1)
        struct.pack_into('<IIHH', data, inode + 52, 0, 20, 0, 0)
        self.assertEqual(reader(data).file(BOOT.MOVIE), b'fixture')
        data[20 * 4096:20 * 4096 + 60] = data[inode + 40:inode + 100]
        with self.assertRaises(ValueError):
            reader(data).file(BOOT.MOVIE)

    def test_rejects_sparse_unwritten_and_overlapping_extents(self):
        for offset, fmt, value in ((52, '<I', 1), (56, '<H', 32769), (56, '<H', 2)):
            data = filesystem()
            struct.pack_into(fmt, data, 2 * 4096 + 2 * 256 + offset, value)
            with self.subTest(offset=offset, value=value), self.assertRaises(ValueError):
                reader(data).file(BOOT.MOVIE)

    def test_raw_partition_and_movie_hash_are_required_without_writing_disk(self):
        with tempfile.TemporaryDirectory() as work:
            disk = Path(work) / 'guest.raw'
            mbr = bytearray(512)
            mbr[510:] = b'\x55\xaa'
            mbr[466] = 0x83
            struct.pack_into('<II', mbr, 470, 1, 256)
            original = mbr + filesystem()
            disk.write_bytes(original)
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                BOOT.read_movie(disk)
            with patch.object(BOOT, 'MOVIE_SHA256', BOOT.hashlib.sha256(b'fixture').hexdigest()):
                self.assertEqual(BOOT.read_movie(disk), b'fixture')
            self.assertEqual(disk.read_bytes(), original)
            mbr[466] = 0
            disk.write_bytes(mbr + filesystem())
            with self.assertRaisesRegex(ValueError, 'partition'):
                BOOT.read_movie(disk)

    def test_reveal_requires_native_acknowledgement_and_propagates_failure(self):
        with tempfile.TemporaryDirectory() as work:
            directory = Path(work)
            BOOT.signal(directory, 'play')
            self.assertEqual((directory / 'phase').read_text(), 'play\n')
            def acknowledge(seconds):
                self.assertEqual((directory / 'phase').read_text(), 'ready\n')
                (directory / 'revealed').write_text('ready\n')
            BOOT.reveal(directory, acknowledge)
            (directory / 'failed').touch()
            with self.assertRaisesRegex(ValueError, 'failed'):
                BOOT.reveal(directory, lambda seconds: None)

    def test_controller_reveals_after_validation_before_input_release(self):
        source = (SCRIPTS / 'diagnose-arm64-shell.py').read_text()
        start = source.index('            if args.interactive:\n')
        interactive = source[start:source.index('            # quit joins', start)]
        reveal = interactive.index('boot_animation.reveal')
        self.assertLess(interactive.index("not home_frames['content_equal']"), reveal)
        self.assertLess(interactive.index('validate_handoff'), reveal)
        self.assertLess(reveal, interactive.index('release=True'))


@unittest.skipUnless(platform.system() == 'Darwin', 'requires native AVFoundation/AppKit')
class BootNativeTests(unittest.TestCase):
    def test_original_player_lifecycle_with_synthetic_media(self):
        with tempfile.TemporaryDirectory(prefix='n00-boot-test-') as work:
            binary = str(Path(work) / 'player-test')
            subprocess.run(['clang', '-Wall', '-Wextra', '-Wno-unused-parameter',
                            '-Wno-unused-function', '-Wno-deprecated-declarations',
                            '-framework', 'Cocoa', '-framework', 'QuartzCore',
                            '-framework', 'AVFoundation', '-framework', 'CoreMedia',
                            '-framework', 'CoreVideo', str(Path(__file__).with_name('boot-animation-host.m')),
                            '-o', binary], check=True, capture_output=True)
            result = subprocess.run([binary, work], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('PASS: boot movie playback, rotation, hold and explicit reveal', result.stdout)


if __name__ == '__main__':
    unittest.main()
