"""FIASCO bounds, variant preservation and original-input protection."""
import hashlib
import importlib.util
import io
from pathlib import Path
import struct
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location(
    "boot_inputs", Path(__file__).resolve().parents[1] / "prepare-boot-inputs.py")
boot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(boot)


def record(payload=b"original", targets=(b"RM-680", b"RM-696"), length=None):
    main = struct.pack(">3BH12sII", 1, 1, 0, 0, b"cmt-2nd", len(payload) if length is None else length, 0)
    fields = [(0x2e, main)] + [(0x32, target.ljust(16, b"\0")) for target in targets]
    header = bytes([len(fields)]) + b"".join(bytes([tag, len(value)]) + value for tag, value in fields)
    return b"T" + header + bytes([(255 - sum(header)) & 255]) + payload


def container(*records):
    header = b"\xe8\x05test\0"
    return b"\xb4" + struct.pack(">II", 4 + len(header), 1) + header + b"".join(records)


class BootInputsTests(unittest.TestCase):
    def inspect(self, data):
        return boot.inspect_fiasco(io.BytesIO(data), len(data))

    def test_repeated_targets_and_same_type_variants_are_preserved(self):
        _, rows = self.inspect(container(record(b"one"), record(b"two")))
        self.assertEqual(len(rows), 2)
        self.assertEqual([x['device'] for x in rows[0]['metadata']], ['RM-680', 'RM-696'])
        self.assertNotEqual(rows[0]['offset'], rows[1]['offset'])

    def test_truncated_and_oversized_payloads_fail(self):
        data = container(record())
        for broken in (data[:4], data[:-1], container(record(length=0xffffffff)), data+b'T'):
            with self.subTest(length=len(broken)), self.assertRaises(ValueError):
                self.inspect(broken)

    def test_header_checksum_and_length_are_required(self):
        data = container(record())
        bad_checksum = bytearray(data)
        bad_checksum[-len(b'original')-1] ^= 1
        bad_length = bytearray(data)
        bad_length[4] += 1
        for broken in (bad_checksum, bad_length):
            with self.assertRaises(ValueError):
                self.inspect(broken)

    def test_malformed_device_field_fails(self):
        with self.assertRaisesRegex(ValueError, 'device/revision'):
            self.inspect(container(record(targets=(b'X'*17,))))

    def test_unknown_type_and_trailing_bytes_fail(self):
        data = container(record())
        altered = data.replace(b'cmt-2nd', b'unknown')
        for broken in (altered, data+b'garbage'):
            with self.assertRaises(ValueError):
                self.inspect(broken)

    def test_hash_failure_creates_no_output(self):
        with tempfile.TemporaryDirectory() as folder:
            source, output = Path(folder)/'firmware', Path(folder)/'new'
            data = container(record())
            source.write_bytes(data)
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                boot.prepare(source, output, {'bytes':len(data), 'sha256':'0'*64})
            self.assertFalse(output.exists())
            self.assertEqual(source.read_bytes(), data)

    def test_preparation_preserves_variants_and_refuses_existing_output(self):
        with tempfile.TemporaryDirectory() as folder:
            source, output = Path(folder)/'firmware', Path(folder)/'new'
            data = container(record(b'one'), record(b'two'))
            source.write_bytes(data)
            identity = {'bytes':len(data), 'sha256':hashlib.sha256(data).hexdigest()}
            result = boot.prepare(source, output, identity)
            self.assertEqual((output/'000-cmt-2nd.bin').read_bytes(), b'one')
            self.assertEqual((output/'001-cmt-2nd.bin').read_bytes(), b'two')
            self.assertFalse(result['kci_selected'])
            self.assertEqual(result['secure_boot'], 'UNVERIFIED')
            before = {p.name:p.read_bytes() for p in output.iterdir()}
            with self.assertRaisesRegex(ValueError, 'already exists'):
                boot.prepare(source, output, identity)
            self.assertEqual(before, {p.name:p.read_bytes() for p in output.iterdir()})
            self.assertEqual(source.read_bytes(), data)
