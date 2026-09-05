import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location('profile_analyzer', Path(__file__).resolve().parents[1] / 'analyze-arm64-profile.py')
PROFILE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROFILE)


class ProfileAnalyzerTests(unittest.TestCase):
    def test_parse_valid_gles_and_optional_prefix(self):
        line = 'n00_profile_gles client=1 api=2 call=31 start_ns=100 dispatch_ns=30 worker_ns=20\n'
        self.assertEqual(PROFILE.parse_line(line)['worker_ns'], 20)
        self.assertEqual(PROFILE.parse_line('12@123.456: '+line)['event'], 'gles')

    def test_unknown_diagnostics_and_malformed_fields_are_not_ignored(self):
        for line in ('N00_GLES unsupported call\n', '', 'n00_profile_unknown start_ns=1 total_ns=2\n',
                     'n00_profile_cocoa_draw start_ns=10 total_ns=-1\n',
                     'n00_profile_cocoa_draw start_ns=10 total_ns=2 total_ns=3\n',
                     'n00_profile_gles client=1 api=2 call=31 start_ns=100 dispatch_ns=10 worker_ns=20\n',
                     'n00_profile_dss start_ns=10 total_ns=20 copy_ns=30 first=0 last=1 cols=864 rows=480\n'):
            with self.assertRaises(ValueError):
                PROFILE.parse_line(line)

    def clocks(self):
        return {'start': dict(python_ns=10_000_000_000, posix_ns=2_000_000_000, posix_minus_python_ns=-8_000_000_000, bracket_ns=40),
                'end': dict(python_ns=20_000_000_000, posix_ns=12_002_000_000, posix_minus_python_ns=-7_998_000_000, bracket_ns=60)}

    def test_separate_clock_origins_and_drift(self):
        self.assertEqual(PROFILE.align_clock(15, self.clocks()), 7_001_000_000)
        with self.assertRaises(ValueError):
            PROFILE.align_clock(9, self.clocks())
        clocks = self.clocks(); clocks['end']['posix_minus_python_ns'] = 0
        with self.assertRaises(ValueError):
            PROFILE.align_clock(15, clocks)

    def test_nearest_rank_quantiles_and_empty_samples(self):
        summary = PROFILE.quantiles([1_000_000, 3_000_000, 2_000_000])
        self.assertEqual((summary['sum_ms'], summary['p50_ms'], summary['p95_ms']), (6, 2, 3))
        self.assertIsNone(PROFILE.quantiles([])['p95_ms'])

    def test_fixed_abi_names(self):
        text = '\n'.join(f'enum n00_{name}_call {{ N00_{name}_first, N00_{name}_second, N00_{name}_count }};' for name in ('egl', 'es11', 'es20'))
        self.assertEqual(PROFILE.wire_names(text)[(2, 1)], 'second')
        with self.assertRaises(ValueError):
            PROFILE.wire_names(text.replace('_first,', '_first = 2,'))

    def test_nested_costs_are_separate_not_added(self):
        record = PROFILE.parse_line('n00_profile_gles client=1 api=2 call=31 start_ns=100 dispatch_ns=30 worker_ns=20')
        result = PROFILE.summarize([record], {(2, 31): 'example'})
        self.assertEqual(result['events']['gles']['transport_remainder_ns']['sum_ms'], .00001)
        self.assertEqual(result['events']['cocoa_draw']['count'], 0)
        with self.assertRaises(ValueError):
            PROFILE.summarize([record], {})

    def test_clock_aligned_window_and_crossing_event_exclusion(self):
        first = PROFILE.align_clock(14, self.clocks())
        records = [dict(event='cocoa_draw', start_ns=first+1000, total_ns=100),
                   dict(event='cocoa_draw', start_ns=first-1000, total_ns=2000)]
        measures = {'trace_profile_enabled': True, 'post_idle_sync': True, 'clock_alignment': self.clocks(),
                    'responses': {'tap': {'first_observed_match_seconds': 1, 'samples': [{'end': 15}]}}}
        result = PROFILE.analyze(records, measures, {})
        self.assertEqual(result['responses']['tap']['events']['cocoa_draw']['count'], 1)
        self.assertEqual(result['whole_run']['events']['cocoa_draw']['count'], 2)
        self.assertNotIn('fps', result)
        with self.assertRaises(ValueError):
            PROFILE.analyze([], measures, {})
        measures['trace_profile_enabled'] = False
        with self.assertRaises(ValueError):
            PROFILE.analyze(records, measures, {})


if __name__ == '__main__':
    unittest.main()
