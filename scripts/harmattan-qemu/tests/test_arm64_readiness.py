import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location('readiness', ROOT / 'scripts/harmattan-qemu/arm64-readiness.py')
READINESS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(READINESS)


class ReadinessTests(unittest.TestCase):
    def run_frames(self, frames, quiet_seconds=.5, timeout=2):
        elapsed = [0]
        frames = iter(frames)

        def drain(seconds):
            elapsed[0] += seconds

        def valid(frame):
            if frame == 'empty':
                raise ValueError('empty frame')

        with patch.object(READINESS.time, 'monotonic', side_effect=lambda: elapsed[0]):
            return READINESS.settle(lambda: next(frames, 'empty'), lambda a, b: a == b,
                                    valid, drain, timeout=timeout, quiet_seconds=quiet_seconds)

    def test_requires_three_stable_nonempty_observations(self):
        result = self.run_frames(['empty', 'loading', 'home', 'home', 'home'])
        self.assertEqual(result['samples'], 5)
        self.assertEqual(result['seconds'], 1)

    def test_changed_or_empty_frame_resets_stability(self):
        result = self.run_frames(['home', 'home', 'empty', 'home', 'home', 'home'])
        self.assertEqual(result['samples'], 6)
        result = self.run_frames(['home', 'home', 'loading', 'home', 'home', 'home'])
        self.assertEqual(result['samples'], 6)

    def test_missing_or_unstable_home_times_out(self):
        for frames in ([], ['empty'] * 20, ['home', 'loading'] * 10):
            with self.subTest(frames=frames), self.assertRaises(TimeoutError):
                self.run_frames(frames)

    def test_initially_static_scrollbar_must_finish_fading(self):
        result = self.run_frames(['scrollbar-visible'] * 9 + ['home'] * 21,
                                 quiet_seconds=5, timeout=8)
        self.assertEqual(result['samples'], 30)
        self.assertEqual(result['seconds'], 7.25)


if __name__ == '__main__':
    unittest.main()
