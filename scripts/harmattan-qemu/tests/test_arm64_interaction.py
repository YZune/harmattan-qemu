import importlib.util
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[3]


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT/'scripts/harmattan-qemu'/filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


LEASE = module('lease_analyzer', 'analyze-arm64-interaction.py')
PROBE = module('lease_probe', 'measure-arm64-interaction.py')


class InteractionTests(unittest.TestCase):
    def input(self, start=10, held=0, accepted=1):
        return dict(event='lease_input', start_ns=start, kind=3, accepted=accepted, held=held)

    def transition(self, start=11, phase=0, reason=0, generation=1, deadline=8_000_000_010):
        return dict(event='lease_transition', start_ns=start, phase=phase, reason=reason,
                    generation=generation, deadline_ns=deadline, options=LEASE.ACTIVITY.ACTIVITY_OPTIONS)

    def records(self):
        return [dict(event='lease_config', enabled=1, timeout_ms=8000), self.input(), self.transition(),
                self.input(100, held=1), dict(event='lease_renew', start_ns=100, generation=1, deadline_ns=8_000_000_100),
                self.transition(8_000_000_200, 1, 1, deadline=8_000_000_100),
                self.input(10_000_000_000), self.transition(10_000_000_001, generation=2, deadline=18_000_000_000),
                self.transition(10_000_000_010, 1, 3, generation=2, deadline=18_000_000_000)]

    def test_parse_all_new_events_and_previous_formats(self):
        records = self.records()
        for record in records:
            line = 'n00_' + record['event'] + ' ' + ' '.join(f'{k}={v}' for k,v in record.items() if k != 'event')
            self.assertEqual(LEASE.parse_line(line), record)
            self.assertEqual(LEASE.parse_line('12@12.000: '+line+'\n'), record)
        self.assertEqual(LEASE.parse_line('n00_activity_lifecycle start_ns=1 phase=0 enabled=0 options=0')['options'], 0)
        self.assertEqual(LEASE.parse_line('n00_profile_cocoa_draw start_ns=1 total_ns=2')['event'], 'cocoa_draw')

    def test_unknown_duplicate_negative_and_sleep_options_are_rejected(self):
        for line in ('unexpected warning', 'n00_lease_other start_ns=1',
                     'n00_lease_config enabled=1 timeout_ms=8000 timeout_ms=8000',
                     'n00_lease_config enabled=1 timeout_ms=1',
                     'n00_lease_input start_ns=0 kind=3 accepted=1 held=0',
                     'n00_lease_input start_ns=1 kind=5 accepted=1 held=0',
                     'n00_lease_input start_ns=1 kind=3 accepted=2 held=0',
                     'n00_lease_renew start_ns=1 generation=0 deadline_ns=10',
                     'n00_lease_renew start_ns=1 generation=1 deadline_ns=-1',
                     'n00_lease_transition start_ns=1 phase=0 reason=1 generation=1 deadline_ns=10 options=15728639',
                     'n00_lease_transition start_ns=1 phase=1 reason=0 generation=1 deadline_ns=10 options=15728639',
                     'n00_lease_transition start_ns=1 phase=0 reason=0 generation=1 deadline_ns=10 options=16777215'):
            with self.assertRaises(ValueError):
                LEASE.parse_line(line)

    def test_idle_release_reacquisition_and_exit_are_paired(self):
        intervals, inputs = LEASE.lifetimes(self.records(), True)
        self.assertEqual([r['generation'] for r in intervals], [1,2])
        self.assertEqual([r['end_reason'] for r in intervals], [1,3])
        self.assertEqual(intervals[0]['renewals'], 1)
        self.assertEqual(intervals[0]['expiry_lateness_ms'], .0001)
        self.assertEqual(len(inputs), 3)

    def test_disabled_observations_never_acquire(self):
        records=[dict(event='lease_config', enabled=0, timeout_ms=8000), self.input(accepted=0)]
        self.assertEqual(LEASE.lifetimes(records, False)[0], [])
        with self.assertRaises(ValueError):
            LEASE.lifetimes([records[0], self.input()], False)

    def test_unpaired_early_overlapping_or_incorrect_deadlines_fail(self):
        records = self.records()
        for invalid in (records[:-1], records[:2], records[1:], records[:1]+records,
                        records[:2]+[self.transition(generation=2)]+records[3:],
                        records[:2]+[self.transition(deadline=8_000_000_011)]+records[3:],
                        records[:5]+[self.transition(8_000_000_099,1,1,deadline=8_000_000_100)]+records[6:],
                        records[:3]+[self.input(100, held=0)]+records[4:],
                        records[:3]+[self.transition(12)]+records[3:],
                        records[:3]+[self.input(9, held=1)]+records[4:]):
            with self.assertRaises(ValueError):
                LEASE.lifetimes(invalid, True)

    def checks(self):
        checks = dict(idle_checks=[dict(after_stage=s, posix_begin_ns=(i*20+1)*10**9,
                                       posix_end_ns=(i*20+11)*10**9)
                                  for i,s in enumerate(PROBE.IDLE_STAGES)],
                      exit_rearm=dict(posix_begin_ns=70*10**9, posix_end_ns=71*10**9))
        intervals=[dict(generation=i+1,begin_ns=i*20*10**9,end_ns=(i*20+8)*10**9,end_reason=1)
                   for i in range(3)]
        intervals.append(dict(generation=4,begin_ns=70*10**9+1,end_ns=72*10**9,
                              deadline_ns=78*10**9,end_reason=3))
        return intervals, checks

    def test_extra_idles_and_active_exit_require_real_transitions(self):
        intervals, checks = self.checks()
        self.assertEqual(len(LEASE.validate_checks(intervals, checks, True)), 3)
        for changed in (intervals[:-1], intervals[1:],
                        [{**intervals[0], 'begin_ns':2*10**9}, *intervals[1:]],
                        [*intervals[:-1], {**intervals[-1], 'end_reason':1}]):
            with self.assertRaises(ValueError):
                LEASE.validate_checks(changed, checks, True)
        checks['idle_checks'][0]['posix_end_ns'] = 2*10**9
        with self.assertRaises(ValueError):
            LEASE.validate_checks(intervals, checks, True)

    def test_input_scope_not_allowed_in_interactive_or_headless_mode(self):
        env=dict(PATH='/usr/bin:/bin', HARMATTAN_UI_PROFILE='1', HARMATTAN_UI_SCANOUT_PROBE='1',
                 HARMATTAN_UI_ACTIVITY_PROBE='1', N00_COCOA_ACTIVITY='0',
                 HARMATTAN_UI_INTERACTION_PROBE='1', N00_COCOA_INTERACTION='1')
        for mode, change in (('interactive',{}), ('--performance-headless-diagnostic',{}),
                             ('--performance-diagnostic',{'N00_COCOA_ACTIVITY':'1'}),
                             ('--performance-diagnostic',{'N00_COCOA_INTERACTION':'invalid'}),
                             ('--performance-diagnostic',{'HARMATTAN_UI_INTERACTION_PROBE':'0'})):
            result=subprocess.run(['/bin/sh',str(ROOT/'scripts/harmattan-qemu/run-arm64-ui.sh'),mode],
                                   env={**env,**change},capture_output=True,text=True,timeout=3)
            self.assertEqual(result.returncode,2,result.stderr)
            self.assertNotIn('Native UI run artifacts:',result.stdout)

    def test_base_probe_and_reference_pixels_are_reused(self):
        self.assertIs(PROBE.FrameProbe, PROBE.BASE.FrameProbe)
        self.assertEqual(PROBE.HOME_RGB, PROBE.BASE.HOME_RGB)
        text=(ROOT/'scripts/harmattan-qemu/measure-arm64-interaction.py').read_text()
        self.assertIn('result = BASE.run_probe',text)
        self.assertNotIn('screendump',text)

    def test_wrapper_waits_outside_base_responses_and_rearms_without_clicking(self):
        qmp = Mock()
        qmp.call.return_value = {'status': 'running'}
        capture, drain = Mock(), Mock()
        samples = [dict(pid=42, cpu_seconds=i, monotonic_seconds=i, rss_kib=1024) for i in range(1,10)]
        def base_probe(qmp, serial, wait_line, capture_idle, *rest):
            for stage in PROBE.IDLE_STAGES:
                capture_idle(stage)
            return {'responses': {'original': 'unchanged'}}
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(PROBE.BASE, 'run_probe', side_effect=base_probe) as base, \
                patch.object(PROBE.BASE, 'sample_process', side_effect=samples):
            result = PROBE.run_probe(qmp, None, None, capture, None, 270, Path(directory),
                                     SimpleNamespace(pid=42), drain, None)
            self.assertTrue((Path(directory)/'interaction-checks.json').exists())
        base.assert_called_once()
        self.assertEqual(result['responses'], {'original': 'unchanged'})
        self.assertEqual([c.args[0] for c in drain.call_args_list], [5,5,5,5,5,5,.25])
        events = qmp.call.call_args_list[-1].args
        self.assertEqual(events[0], 'input-send-event')
        self.assertEqual([e['type'] for e in events[1]['events']], ['abs','abs'])

    def test_source_uses_input_not_rendering_and_nonblocking_bql_handoff(self):
        source=(ROOT/'ports/qemu-n00/qemu-9.1.3-n00-interaction-activity.patch').read_text()
        self.assertIn('notifier_list_notify(&input_event_notifiers, evt)',source)
        self.assertIn('n00_interaction_deadline = now + N00_INTERACTION_NS',source)
        self.assertIn('n00_interaction_release(1)',source)
        self.assertIn('n00_interaction_release(3)',source)
        self.assertIn('NSWindowDidMiniaturizeNotification',source)
        self.assertIn('qemu_input_remove_event_notifier',source)
        self.assertNotIn('cocoa_update(',source)
        callback=source[source.index('+static void n00_interaction_notify'):source.index('+static Notifier n00_interaction_notifier')]
        self.assertIn('dispatch_async',callback)
        self.assertNotIn('dispatch_sync',callback)


if __name__ == '__main__':
    unittest.main()
