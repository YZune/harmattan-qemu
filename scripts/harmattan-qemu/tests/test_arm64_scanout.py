import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock, patch


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


SCANOUT = module('scanout_analyzer', 'analyze-arm64-scanout.py')
MATRIX = module('scanout_matrix', 'run-arm64-scanout-matrix.py')


class ScanoutTests(unittest.TestCase):
    def test_original_profile_records_still_use_strict_parser(self):
        self.assertEqual(SCANOUT.parse_line('n00_profile_cocoa_draw start_ns=1 total_ns=2')['event'], 'cocoa_draw')
        with self.assertRaises(ValueError):
            SCANOUT.parse_line('n00_profile_cocoa_draw start_ns=1 total_ns=-2')

    def test_scanout_fields_and_pending_mask_are_checked(self):
        record = SCANOUT.parse_line('n00_scanout_frame start_ns=1 enabled=6 pending=2')
        self.assertEqual(record['pending'], 2)
        for line in ('n00_scanout_frame start_ns=1 enabled=4 pending=2',
                     'n00_scanout_frame start_ns=1 enabled=4 pending=0 pending=0',
                     'n00_scanout_frame start_ns=0 enabled=4 pending=0',
                     'n00_scanout_dss_config timer_only=2',
                     'n00_scanout_cocoa_config interval_ms=1',
                     'unexpected diagnostic', 'n00_scanout_frame start_ns=1 enabled=0'):
            with self.assertRaises(ValueError):
                SCANOUT.parse_line(line)

    def test_pending_requests_are_not_called_delivered_interrupts(self):
        records = [dict(enabled=2, pending=0), dict(enabled=2, pending=2)]
        result = SCANOUT.frame_requests(records)
        self.assertEqual(result['requests'], 2)
        self.assertEqual(result['requests_with_enabled_pending_bits'], 1)
        self.assertIn('not delivered', result['scope'])

    def test_configuration_must_be_recorded_exactly_once(self):
        environment = dict(N00_SCANOUT_TIMER_ONLY='1', N00_SCANOUT_REFRESH_MS='33')
        for records in ([], [dict(event='scanout_dss_config', timer_only=0)],
                        [dict(event='scanout_dss_config', timer_only=1)] * 2,
                        [dict(event='scanout_dss_config', timer_only=1)]):
            with self.assertRaises(ValueError):
                SCANOUT.analyze(records, {}, {}, environment, False)

    def test_fast_failure_and_false_graphics_pass_are_rejected(self):
        app = dict(functional_checks_passed=True, host_graphics_clean=False, passed=False,
                   qemu_exit=0, measurements={'post_idle_sync': True})
        MATRIX.validate_result(2, app)
        for key, value in (('functional_checks_passed', False), ('host_graphics_clean', True),
                           ('passed', True), ('qemu_exit', 1), ('measurements', {'post_idle_sync': False})):
            with self.assertRaises(ValueError):
                MATRIX.validate_result(2, {**app, key: value})
        with self.assertRaises(ValueError):
            MATRIX.validate_result(0, app)

    def test_launcher_has_one_trace_option_not_overwriting_file(self):
        script = (Path(__file__).resolve().parents[1] / 'run-arm64-ui.sh').read_text()
        self.assertEqual(script.count('set -- "$@" -trace '), 1)
        self.assertIn('file=$run_root/profile.log', script)
        self.assertIn('trace_pattern=n00_profile_\\*', script)

    def test_background_policy_targets_only_verified_private_headless_child(self):
        controller = Mock(pid=100)
        controller.poll.return_value = None
        log = Mock()
        log.read_text.return_value = 'Native UI run artifacts: /tmp/run.test\nDIAGNOSTIC: bootstrap exit=0;\n'
        listing = '101 100 /tmp/qemu-arm -drive file=/tmp/run.test/pr13-32g.qcow2 -display none\n'
        result = Mock(returncode=0, stdout='', stderr='')
        with patch.object(MATRIX.subprocess, 'check_output', return_value=listing), \
                patch.object(MATRIX.subprocess, 'run', return_value=result) as request:
            record = MATRIX.background_private_child(controller, log, Path('/tmp/qemu-arm'))
        self.assertEqual(record['command'], ['/usr/sbin/taskpolicy', '-b', '-p', '101'])
        request.assert_called_once()

    def test_wrong_or_ambiguous_process_cannot_receive_policy_change(self):
        controller = Mock(pid=100)
        controller.poll.return_value = None
        log = Mock()
        log.read_text.return_value = 'Native UI run artifacts: /tmp/run.test\nDIAGNOSTIC: bootstrap exit=0;\n'
        valid = '101 100 /tmp/qemu-arm -drive file=/tmp/run.test/pr13-32g.qcow2 -display none\n'
        for listing in ('', valid * 2, valid.replace('101 100', '101 200'),
                        valid.replace('/tmp/run.test/', '/tmp/user-session/'),
                        valid.replace('-display none', '-display cocoa'), valid.replace('/tmp/qemu-arm ', '/tmp/other ')):
            with patch.object(MATRIX.subprocess, 'check_output', return_value=listing), \
                    patch.object(MATRIX.subprocess, 'run') as request:
                with self.assertRaises(ValueError):
                    MATRIX.background_private_child(controller, log, Path('/tmp/qemu-arm'))
                request.assert_not_called()


if __name__ == '__main__':
    unittest.main()
