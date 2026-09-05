import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location('activity_analyzer', ROOT / 'scripts/harmattan-qemu/analyze-arm64-activity.py')
ACTIVITY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ACTIVITY)


class ActivityTests(unittest.TestCase):
    def environment(self, enabled='1'):
        return dict(HARMATTAN_UI_ACTIVITY_PROBE='1', HARMATTAN_UI_SCANOUT_PROBE='1',
                    HARMATTAN_UI_PROFILE='1', N00_COCOA_ACTIVITY=enabled,
                    N00_SCANOUT_TIMER_ONLY='0', N00_SCANOUT_REFRESH_MS='0')

    def lifecycle(self, enabled=1):
        return [dict(event='activity_lifecycle', start_ns=10, phase=0,
                     enabled=enabled, options=ACTIVITY.ACTIVITY_OPTIONS * enabled),
                dict(event='activity_lifecycle', start_ns=100, phase=1,
                     enabled=enabled, options=ACTIVITY.ACTIVITY_OPTIONS * enabled)]

    def test_old_trace_formats_keep_strict_validation(self):
        self.assertEqual(ACTIVITY.parse_line('n00_scanout_frame start_ns=1 enabled=0 pending=0')['event'], 'scanout_frame')
        self.assertEqual(ACTIVITY.parse_line('n00_profile_cocoa_draw start_ns=1 total_ns=2')['event'], 'cocoa_draw')
        for line in ('n00_profile_cocoa_draw start_ns=1 total_ns=-1',
                     'n00_scanout_frame start_ns=1 enabled=0 pending=1'):
            with self.assertRaises(ValueError):
                ACTIVITY.parse_line(line)

    def test_valid_activity_records_and_optional_prefix(self):
        line = f'n00_activity_lifecycle start_ns=10 phase=0 enabled=1 options={ACTIVITY.ACTIVITY_OPTIONS}\n'
        self.assertEqual(ACTIVITY.parse_line('42@12.000: ' + line), self.lifecycle()[0])
        record = ACTIVITY.parse_line('n00_activity_observe start_ns=20 active=0 window_visible=1 occlusion=8192')
        self.assertEqual(record['occlusion'], 8192)

    def test_unknown_malformed_or_invalid_records_fail(self):
        for line in ('unexpected warning', '', 'n00_activity_unknown start_ns=1',
                     'n00_activity_observe start_ns=1 active=0 active=1 window_visible=1 occlusion=0',
                     'n00_activity_observe start_ns=0 active=0 window_visible=1 occlusion=0',
                     'n00_activity_observe start_ns=1 active=2 window_visible=1 occlusion=0',
                     'n00_activity_observe start_ns=1 active=0 window_visible=2 occlusion=0',
                     'n00_activity_observe start_ns=1 active=0 window_visible=1 occlusion=-1',
                     f'n00_activity_observe start_ns=1 active=0 window_visible=1 occlusion={1 << 64}',
                     'n00_activity_lifecycle start_ns=1 phase=2 enabled=0 options=0',
                     'n00_activity_lifecycle start_ns=1 phase=0 enabled=2 options=0',
                     'n00_activity_lifecycle start_ns=1 phase=0 enabled=0 options=1'):
            with self.assertRaises(ValueError):
                ACTIVITY.parse_line(line)

    def test_sleep_and_latency_flags_are_never_accepted(self):
        self.assertFalse(ACTIVITY.ACTIVITY_OPTIONS & ((1 << 20) | (1 << 40) | 0xFF00000000))
        for extra in (1 << 20, 1 << 40, 0xFF00000000):
            with self.assertRaises(ValueError):
                ACTIVITY.parse_line(f'n00_activity_lifecycle start_ns=1 phase=0 enabled=1 options={ACTIVITY.ACTIVITY_OPTIONS | extra}')

    def test_enabled_and_disabled_begins_and_ends_are_paired(self):
        for enabled in (0, 1):
            records = self.lifecycle(enabled)
            self.assertEqual(ACTIVITY.validate_lifecycle(records, self.environment(str(enabled))), records)

    def test_missing_duplicate_reversed_or_mismatched_lifecycle_fails(self):
        records = self.lifecycle()
        for invalid in ([], records[:1], records * 2, list(reversed(records)),
                        [records[0], {**records[1], 'enabled': 0, 'options': 0}],
                        [records[0], {**records[1], 'start_ns': 10}]):
            with self.assertRaises(ValueError):
                ACTIVITY.validate_lifecycle(invalid, self.environment())
        for change in (dict(N00_COCOA_ACTIVITY='0'), dict(N00_COCOA_ACTIVITY='yes'),
                       dict(HARMATTAN_UI_ACTIVITY_PROBE='0'), dict(HARMATTAN_UI_PROFILE='0')):
            with self.assertRaises(ValueError):
                ACTIVITY.validate_lifecycle(records, {**self.environment(), **change})

    def test_observation_counts_do_not_imply_continuous_visibility_or_fps(self):
        result = ACTIVITY.observations([dict(start_ns=20, active=0, window_visible=1, occlusion=0)] * 2)
        self.assertEqual(result['count'], 2)
        self.assertEqual(result['states'][0]['count'], 2)
        self.assertIn('not continuous visibility', result['scope'])
        self.assertIsNone(ACTIVITY.observations([])['first_ns'])

    def test_clock_aligned_observations_and_lifetime_coverage(self):
        records = self.lifecycle() + [dict(event='activity_observe', start_ns=20, active=0, window_visible=1, occlusion=0),
                                      dict(event='activity_observe', start_ns=80, active=0, window_visible=1, occlusion=0)]
        result = dict(whole_run={}, responses={'tap': dict(posix_begin_ns=15, posix_end_ns=30)})
        with patch.object(ACTIVITY.SCANOUT, 'analyze', return_value=result):
            output = ACTIVITY.analyze(records, {}, {}, self.environment())
        self.assertEqual(output['whole_run']['appkit_observations']['count'], 2)
        self.assertEqual(output['responses']['tap']['appkit_observations']['count'], 1)
        self.assertNotIn('fps', output)
        for invalid in (records[:2], records + [{**records[2], 'start_ns': 101}],
                        records + [dict(event='unknown')]):
            with self.assertRaises(ValueError):
                ACTIVITY.analyze(invalid, {}, {}, self.environment())
        result['responses']['tap']['posix_end_ns'] = 101
        with patch.object(ACTIVITY.SCANOUT, 'analyze', return_value=result):
            with self.assertRaises(ValueError):
                ACTIVITY.analyze(records, {}, {}, self.environment())

    def test_launcher_rejects_unbounded_or_incomplete_activity_before_starting_qemu(self):
        script = ROOT / 'scripts/harmattan-qemu/run-arm64-ui.sh'
        for mode, values in (('interactive', {'N00_COCOA_ACTIVITY': '1'}),
                             ('interactive', self.environment()),
                             ('--performance-headless-diagnostic', self.environment()),
                             ('--performance-diagnostic', {**self.environment(), 'N00_COCOA_ACTIVITY': ''}),
                             ('--performance-diagnostic', {**self.environment(), 'HARMATTAN_UI_SCANOUT_PROBE': '0'})):
            result = subprocess.run(['/bin/sh', str(script), mode],
                                    env={'PATH': '/usr/bin:/bin', **values}, capture_output=True, text=True, timeout=3)
            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertNotIn('Native UI run artifacts:', result.stdout)

    def test_opt_in_source_has_paired_activity_and_no_direct_qos_or_activation(self):
        patch_text = (ROOT / 'ports/qemu-n00/qemu-9.1.3-n00-activity-probe.patch').read_text()
        self.assertIn('NSActivityUserInitiatedAllowingIdleSystemSleep', patch_text)
        self.assertIn('endActivity:n00_activity_token', patch_text)
        self.assertIn('n00_activity_end();', patch_text)
        for unwanted in ('set_qos', 'activateIgnoringOtherApps', 'NSActivityLatencyCritical', 'defaults write'):
            self.assertNotIn(unwanted, patch_text)
        script = (ROOT / 'scripts/harmattan-qemu/run-arm64-ui.sh').read_text()
        self.assertIn('activity_probe=${HARMATTAN_UI_ACTIVITY_PROBE:-0}', script)
        self.assertIn('qemu-9.1.3/build-arm64-cocoa', script)
        self.assertIn('idle=${HARMATTAN_UI_IDLE:-$default_idle}', script)
        self.assertIn('default_idle=spin', script)


if __name__ == '__main__':
    unittest.main()
