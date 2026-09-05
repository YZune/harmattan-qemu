import importlib.util
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location('ui_performance', Path(__file__).resolve().parents[1] / 'measure-arm64-ui.py')
PERF = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PERF)


class PerformanceMeasurementTests(unittest.TestCase):
    def thread_samples(self):
        before = dict(pid=42, posix_before_ns=1, posix_after_ns=2, threads=[
            dict(thread_handle=7, name='CPU 0/TCG', user_time_ns=100, system_time_ns=50, priority=4)])
        after = dict(pid=42, posix_before_ns=10, posix_after_ns=11, threads=[
            dict(thread_handle=7, name='CPU 0/TCG', user_time_ns=1000100, system_time_ns=2000050, priority=31)])
        return before, after

    def test_thread_cpu_delta_is_not_wall_time_or_priority_inference(self):
        result = PERF.summarize_threads(*self.thread_samples())
        self.assertAlmostEqual(result['matched_cpu_seconds'], .003)
        self.assertEqual(result['matched_threads'][0]['name'], 'CPU 0/TCG')
        self.assertEqual(result['new_thread_handles'], [])

    def test_thread_churn_is_explicit_not_silently_counted_as_zero(self):
        before, after = self.thread_samples()
        after['threads'][0]['thread_handle'] = 9
        result = PERF.summarize_threads(before, after)
        self.assertEqual(result['new_thread_handles'], [9])
        self.assertEqual(result['exited_thread_handles'], [7])
        self.assertEqual(result['matched_threads'], [])

    def test_thread_identity_time_and_counter_errors_fail(self):
        for mutation in ('pid', 'clock', 'duplicate', 'counter', 'name'):
            before, after = self.thread_samples()
            if mutation == 'pid': after['pid'] = 44
            if mutation == 'clock': after['posix_before_ns'] = 2
            if mutation == 'duplicate': after['threads'] *= 2
            if mutation == 'counter': after['threads'][0]['user_time_ns'] = 0
            if mutation == 'name': after['threads'][0]['name'] = 'different'
            with self.assertRaises(ValueError):
                PERF.summarize_threads(before, after)

    def test_clock_alignment_records_distinct_origins(self):
        sample = PERF.clock_alignment()
        self.assertGreater(sample['python_ns'], 0)
        self.assertGreater(sample['posix_ns'], 0)
        self.assertGreaterEqual(sample['bracket_ns'], 0)
        self.assertEqual(sample['posix_minus_python_ns'], sample['posix_ns'] - sample['python_ns'])

    def plane(self):
        return dict(base=0x8093a000, position=0, size=(479 << 16) | 863,
                    attributes=0x91, row_inc=1, pixel_inc=1)

    def test_cpu_time_formats(self):
        for text, seconds in (('01:02.30', 62.3), ('70:00.00', 4200),
                              ('02:03:04.50', 7384.5), ('1-02:03:04', 93784)):
            self.assertAlmostEqual(PERF.cpu_seconds(text), seconds)
        for text in ('', 'abc', '-1:00', '00:00junk'):
            with self.assertRaises(ValueError):
                PERF.cpu_seconds(text)

    def test_process_identity_and_rss(self):
        self.assertEqual(PERF.parse_process('42 1:02.50 614400', 42)['rss_kib'], 614400)
        for text in ('43 1:02.50 614400', '42 1:02.50 0', '', '42 0:01.0 20 extra'):
            with self.assertRaises(ValueError):
                PERF.parse_process(text, 42)

    def test_cpu_percent_uses_delta_not_lifetime_or_host_core_count(self):
        values = [dict(pid=42, monotonic_seconds=100, cpu_seconds=5000, rss_kib=614400),
                  dict(pid=42, monotonic_seconds=115, cpu_seconds=5000.75, rss_kib=615424)]
        result = PERF.summarize_cpu(values)
        self.assertEqual(result['one_core_percent'], 5)
        self.assertEqual(result['rss_mib_range'], [600, 601])
        values[1]['cpu_seconds'] = 5018
        self.assertEqual(PERF.summarize_cpu(values)['one_core_percent'], 120)

    def test_invalid_cpu_sample_sequences_rejected(self):
        first = dict(pid=42, monotonic_seconds=100, cpu_seconds=100, rss_kib=1024)
        second = dict(pid=42, monotonic_seconds=115, cpu_seconds=105, rss_kib=1024)
        for values in ([], [first], [first, first], [second, first],
                       [first, dict(second, pid=43)], [first, dict(second, cpu_seconds=99)]):
            with self.assertRaises(ValueError):
                PERF.summarize_cpu(values)

    def test_memory_span_stays_inside_sdram(self):
        plane = self.plane()
        self.assertEqual(PERF.validate_plane(plane), plane['base'])
        for address in (0, 0x48050480, 0x7ffffffc, 0x9ffff000, 0x80000001):
            with self.assertRaises(ValueError):
                PERF.validate_plane(dict(plane, base=address))

    def test_wrong_pixel_layout_is_not_a_latency_result(self):
        for name, value in (('size', (863 << 16) | 479), ('position', 1),
                            ('row_inc', 3456), ('pixel_inc', 4),
                            ('attributes', 0x90), ('attributes', 0x8d),
                            ('attributes', 0x191), ('attributes', 0x291)):
            with self.assertRaises(ValueError):
                PERF.validate_plane(dict(self.plane(), **{name: value}))

    def test_guest_bgrx_mapping_ignores_unused_high_byte(self):
        data = bytes((1, 2, 3, 99)) * (PERF.WIDTH * PERF.HEIGHT)
        self.assertEqual(PERF.framebuffer_rgb(data), bytes((3, 2, 1)) * (PERF.WIDTH * PERF.HEIGHT))
        with self.assertRaises(ValueError):
            PERF.framebuffer_rgb(data[:-1])

    def test_first_matching_observation_does_not_claim_exact_fps(self):
        probe = object.__new__(PERF.FrameProbe)
        now = PERF.time.monotonic()
        probe.qmp = type('FakeQMP', (), dict(deadline=now + 10))()
        reads = iter([dict(start=now, end=now + .01, rgb_sha256='old'),
                      dict(start=now + .1, end=now + .11, rgb_sha256='new')])
        probe.read = lambda: next(reads)
        probe.drain = lambda seconds: None
        result = probe.wait_for('new', now, now + .02)
        self.assertEqual(result['sample_count'], 2)
        self.assertAlmostEqual(result['first_observed_match_seconds'], .11)
        self.assertAlmostEqual(result['last_nonmatching_sample_seconds'], .01)
        self.assertNotIn('fps', result)

    def test_timeout_is_failure_not_a_fast_response(self):
        probe = object.__new__(PERF.FrameProbe)
        probe.qmp = type('FakeQMP', (), dict(deadline=PERF.time.monotonic() - 1))()
        with self.assertRaises(TimeoutError):
            probe.wait_for('reference', PERF.time.monotonic())

    def test_transient_match_does_not_satisfy_stability_gate(self):
        probe = object.__new__(PERF.FrameProbe)
        now = PERF.time.monotonic()
        probe.qmp = type('FakeQMP', (), dict(deadline=now + 10))()
        reads = iter([dict(end=now, rgb_sha256='reference'),
                      dict(end=now + .3, rgb_sha256='scrollbar'),
                      dict(end=now + .4, rgb_sha256='reference'),
                      dict(end=now + .8, rgb_sha256='reference'),
                      dict(end=now + 1.1, rgb_sha256='reference')])
        probe.read = lambda: next(reads)
        probe.drain = lambda seconds: None
        result = probe.wait_stable('reference')
        self.assertEqual(len(result['samples']), 5)
        self.assertAlmostEqual(result['observed_stable_seconds'], .7)

    def test_stability_timeout_is_failure(self):
        probe = object.__new__(PERF.FrameProbe)
        probe.qmp = type('FakeQMP', (), dict(deadline=PERF.time.monotonic() - 1))()
        with self.assertRaises(TimeoutError):
            probe.wait_stable('reference')


if __name__ == '__main__':
    unittest.main()
