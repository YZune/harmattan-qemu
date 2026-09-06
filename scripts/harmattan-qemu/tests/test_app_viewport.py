import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('app_viewport', SCRIPTS / 'arm64-app-viewport.py')
VIEWPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VIEWPORT)
HOST_SPEC = importlib.util.spec_from_file_location('viewport_host_fixture', Path(__file__).with_name('test_arm64_systemui.py'))
HOST = importlib.util.module_from_spec(HOST_SPEC)
HOST_SPEC.loader.exec_module(HOST)

READER_CYCLE = (b'N00_GLES connect client=4 abi=2\n'
                b'N00_GLES current client=4 es=2 renderer=Apple Test GPU\n'
                b'N00_GLES terminate client=4 released=1 backend=retained\n'
                b'N00_GLES terminate client=4 rejected=bad-display\n'
                b'N00_GLES disconnect client=4\n')


def reader_host(cycles=1):
    return HOST.host().replace(b'N00_GLES disconnect client=1\n',
                               READER_CYCLE * cycles + b'N00_GLES disconnect client=1\n', 1)


class AppViewportTests(unittest.TestCase):
    def test_reader_cycles_are_complete_and_base_gate_remains_strict(self):
        result = VIEWPORT.validate_host(reader_host(2), 2)
        self.assertTrue(result['clean'])
        self.assertEqual(result['reader_lifecycles'], 2)
        self.assertEqual(result['base_ui_gpu_contexts'], 3)
        self.assertEqual(result['peak_gpu_contexts'], 4)
        with self.assertRaises(ValueError):
            VIEWPORT.systemui.validate_host(reader_host())

    def test_reader_warnings_bad_abi_and_incomplete_teardown_fail(self):
        data = reader_host()
        for old, new in ((b'client=4 abi=2', b'client=4 abi=1'),
                         (b'client=4', b'client=5'),
                         (b'renderer=Apple', b'renderer=Software'),
                         (b'client=4 rejected=bad-display', b'client=4 rejected=current-context'),
                         (b'N00_GLES disconnect client=4\n', b''),
                         (b'rejects=0', b'rejects=1'), (b'faults=0', b'faults=1'),
                         (b'workers=joined', b'workers=pending')):
            with self.subTest(old=old), self.assertRaises(ValueError):
                VIEWPORT.validate_host(data.replace(old, new), 1)
        for changed in (data + b'warning\n', b'warning\n' + data,
                        data.replace(READER_CYCLE, READER_CYCLE.replace(b'current client=4', b'unsupported current client=4')),
                        data.replace(READER_CYCLE, b'') + READER_CYCLE):
            with self.assertRaises(ValueError):
                VIEWPORT.validate_host(changed, 1)

    def test_reader_count_must_match_independent_launch_evidence(self):
        for count in (0, 2, 9, True, 1.0):
            with self.subTest(count=count), self.assertRaises(ValueError):
                VIEWPORT.validate_host(reader_host(), count)
        with self.assertRaises(ValueError):
            VIEWPORT.validate_host(HOST.host(), 1)

    def test_only_verified_reader_gl_viewport_is_replaced_and_released(self):
        with tempfile.TemporaryDirectory(prefix='harmattan-app-viewport-') as temporary:
            binary = str(Path(temporary) / 'probe')
            subprocess.run(['cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                            str(SCRIPTS / 'app-viewport-guest.c'),
                            str(SCRIPTS / 'tests/app-viewport-host.c'), '-o', binary], check=True)
            for mode in range(11):
                with self.subTest(mode=mode):
                    result = subprocess.run([binary, str(mode)], timeout=5, capture_output=True)
                    self.assertEqual(result.returncode, 122 if 5 <= mode <= 8 else 0, result.stderr)
                    if mode == 0:
                        self.assertEqual(result.stdout, b'N00_APP_VIEWPORT_FB_READER_RASTER\n')
                    else:
                        self.assertEqual(result.stdout, b'')

    def test_preparation_binds_guest_shell_to_exact_helper(self):
        with tempfile.TemporaryDirectory(prefix='harmattan-app-prepare-') as temporary:
            root = Path(temporary)
            binary = root / 'app-viewport-guest/n00-app-viewport.so'
            binary.parent.mkdir()
            data = bytearray(64)
            data[:7] = b'\x7fELF\x01\x01\x01'
            data[16:20] = b'\x03\x00\x28\x00'
            binary.write_bytes(data)
            with patch.dict(os.environ, HARMATTAN_PREBUILT_HELPERS='', HARMATTAN_PORT_WORKSPACE=temporary), \
                    patch.object(VIEWPORT.subprocess, 'run'):
                payloads, info = VIEWPORT.prepare()
                self.assertEqual(payloads['n00-app-viewport.so'], data)
                self.assertIn(info['helper_md5'].encode(), payloads['app-viewport-guest.sh'])
                self.assertNotIn(b'@HELPER_MD5@', payloads['app-viewport-guest.sh'])
                for malformed in (b'', bytes(64), data[:16] + b'\x02\x00\x28\x00' + data[20:]):
                    binary.write_bytes(malformed)
                    with self.assertRaises(ValueError):
                        VIEWPORT.prepare()
