"""Live frontend startup failures never leave a healthy-looking session."""
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from test_linux_ui import SHELL, RENDERER


class StartupLifecycleTests(unittest.TestCase):
    def test_live_mode_requires_offline_upright_bounded_snapshot(self):
        args = SimpleNamespace(host_backend='linux-offscreen', host_renderer=RENDERER,
            systemui_attempts=30, network='off', audio='off', ca_certificates='off',
            profile=None, boot_animation=None, power='off', call_simulation='off',
            lockscreen='off', startup_waits='ready', interactive=True, exit_on_ready=False,
            exercise_keyboard=False, exercise_transitions=False, rotation=270, timeout=1800,
            linux_live_session=Path('session'), linux_live_metrics=True)
        command = ['qemu', '-display', 'none', '-nic', 'none', '-snapshot']
        with patch.object(SHELL.sys, 'platform', 'linux'), patch.object(SHELL.linux_offscreen, 'require_pillow'):
            self.assertTrue(SHELL.validate_host_configuration(args, command))
            for key, value in (('network', 'user'), ('rotation', 0), ('timeout', 1801),
                               ('timeout', float('nan')), ('interactive', False),
                               ('exit_on_ready', True), ('linux_live_session', None),
                               ('host_backend', 'cocoa')):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    SHELL.validate_host_configuration(SimpleNamespace(**(vars(args) | {key: value})), command)

    def test_pre_qemu_failure_is_terminal_and_heartbeat_stops(self):
        for error in (RuntimeError('helper preparation failed'), SystemExit(2)):
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                session = root / 'session'
                observed = []
                def fail(args, command, linux, bridge, parser):
                    observed.append(bridge)
                    self.assertEqual(bridge.state['state'], 'starting')
                    self.assertTrue(bridge.heartbeat_thread.is_alive())
                    raise error
                argv = ['diagnose-arm64-shell.py', '--output', str(root / 'out'),
                        '--linux-live-session', str(session), '--linux-live-metrics', '--', 'qemu']
                with patch.object(sys, 'argv', argv), patch.object(SHELL, 'validate_host_configuration', return_value=True), \
                     patch.object(SHELL, 'run_session', side_effect=fail), self.assertRaises(type(error)):
                    SHELL.main()
                status = json.loads((session / 'status.json').read_text())
                self.assertEqual(status['state'], 'error')
                self.assertFalse(status['ready'])
                self.assertFalse(status['passed'])
                self.assertFalse(observed[0].heartbeat_thread.is_alive())
                self.assertTrue(observed[0].metrics_enabled)

    def test_cancelled_startup_remains_cancelled(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def cancel(args, command, linux, bridge, parser):
                bridge.finish(False, state='cancelled')
                raise RuntimeError('cancelled')
            argv = ['diagnose-arm64-shell.py', '--output', str(root / 'out'),
                    '--linux-live-session', str(root / 'session'), '--', 'qemu']
            with patch.object(sys, 'argv', argv), patch.object(SHELL, 'validate_host_configuration', return_value=True), \
                 patch.object(SHELL, 'run_session', side_effect=cancel), self.assertRaises(RuntimeError):
                SHELL.main()
            self.assertEqual(json.loads((root / 'session/status.json').read_text())['state'], 'cancelled')

    def test_serial_wait_checks_cancellation_before_blocking(self):
        sentinel = RuntimeError('cancel startup')
        with patch.object(SHELL.display.select, 'select') as select_call:
            with self.assertRaisesRegex(RuntimeError, 'cancel startup'):
                SHELL.display.wait_serial(None, None, io.BytesIO(), lambda data: False,
                    time.monotonic() + 10, checkpoint=lambda: (_ for _ in ()).throw(sentinel))
            select_call.assert_not_called()


if __name__ == '__main__':
    unittest.main()
