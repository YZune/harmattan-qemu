import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('lockscreen', Path(__file__).resolve().parents[1] / 'arm64-lockscreen.py')
LOCK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LOCK)
REPORT = b'N00_LOCKSCREEN window=00600020 pid=269 mapped=1 low_power=1\n'


class LockScreenTests(unittest.TestCase):
    def test_original_identity_and_state_are_required(self):
        self.assertTrue(LOCK.parse_report(REPORT, 269)['low_power'])
        for data in (b'', REPORT * 2, REPORT.replace(b'low_power=1', b'low_power=7'),
                     REPORT.replace(b'00600020', b'00000000')):
            with self.subTest(data=data), self.assertRaises(ValueError):
                LOCK.parse_report(data, 269)
        with self.assertRaisesRegex(ValueError, 'process changed'):
            LOCK.parse_report(REPORT, 270)

    def test_mailbox_rejects_malformed_and_symlink_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            control = LOCK.Control(Path(directory))
            path = control.directory / 'request'
            self.assertFalse(control.pending())
            for value in (b'', b'press', b'press\nextra', b'other\n'):
                path.write_bytes(value)
                with self.subTest(value=value), self.assertRaises(ValueError):
                    control.pending()
            path.unlink()
            target = Path(directory) / 'unrelated'
            target.write_bytes(b'press\n')
            path.symlink_to(target)
            with self.assertRaises(OSError):
                control.pending()
            self.assertEqual(target.read_bytes(), b'press\n')

    def test_guest_failure_cannot_acknowledge_a_press(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            control = LOCK.Control(root)
            request = control.directory / 'request'
            request.write_bytes(b'press\n')
            class Serial:
                def sendall(self, data):
                    (root / 'serial.log').write_bytes(b'N00_LOCK_PHASE_1_BEGIN\n' + REPORT +
                        b'N00_LOCK_PHASE_1_EXIT_1\nN00_LOCK_PHASE_1_DONE\n')
            with self.assertRaisesRegex(ValueError, 'action failed'):
                control.consume(Serial(), lambda marker: None)
            self.assertTrue(request.exists())
            self.assertEqual(control.info['actions'], [])

    def test_native_producer_readiness_coalescing_and_acknowledgement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / 'control'
            subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', str(Path(__file__).with_name('lockscreen-host.c')),
                            '-o', str(binary)], check=True, capture_output=True)
            control = LOCK.Control(root)
            def native(action):
                return subprocess.check_output([str(binary), action], env=os.environ | control.environment())
            self.assertEqual(native('ready'), b'0\n')
            self.assertEqual(native('press'), b'0\n')
            self.assertFalse(control.pending())
            control.enable()
            self.assertEqual(native('ready'), b'1\n')
            self.assertEqual(native('press'), b'1\n')
            request = control.directory / 'request'
            before = request.stat().st_ino
            self.assertEqual(native('press'), b'1\n')
            self.assertEqual(request.stat().st_ino, before)
            self.assertTrue(control.pending())
            request.unlink()
            self.assertEqual(native('press'), b'1\n')
            self.assertTrue(control.pending())
            control.close()
            self.assertEqual(native('press'), b'0\n')
            self.assertEqual(request.read_bytes(), b'press\n')


if __name__ == '__main__':
    unittest.main()
