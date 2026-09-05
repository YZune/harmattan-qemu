import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('animations', SCRIPTS / 'arm64-animations.py')
ANIMATIONS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ANIMATIONS)


def report(events):
    return b'\nN00_ANIMATIONS_BEGIN\n' + events + b'\nN00_ANIMATIONS_END\n'


def cycle(n):
    return f'N00_COMPOSITOR_HANDOFF_PRESENTED id={n}\nN00_COMPOSITOR_HANDOFF_RELEASED id={n}\n'.encode()


class HandoffTests(unittest.TestCase):
    def test_history_repeats_without_counting_snapshots_as_cycles(self):
        data = report(b'') + report(cycle(1)) * 3 + report(cycle(1) + cycle(2))
        result = ANIMATIONS.validate_handoff(data, minimum=2)
        self.assertEqual(result['completed'], 2)
        self.assertEqual(result['retained_pixmaps_pending'], 0)
        self.assertIn('independent gates', result['scope'])

    def test_missing_reordered_leaked_or_rewritten_history_fails(self):
        good = report(cycle(1))
        for bad in (b'', report(b''), good.replace(b'RELEASED', b'MISSING'),
                    good.replace(b'PRESENTED', b'RELEASED'), good.replace(b'id=1', b'id=2'),
                    good + report(b''), good + b'N00_COMPOSITOR_HANDOFF_ERROR',
                    good + b'\nN00_ANIMATIONS_BEGIN\n', report(cycle(1) + b'N00_COMPOSITOR_HANDOFF_BAD\n')):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                ANIMATIONS.validate_handoff(bad)
        with self.assertRaises(ValueError):
            ANIMATIONS.validate_handoff(good, minimum=2)
        for minimum in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                ANIMATIONS.validate_handoff(good, minimum=minimum)

    def test_actual_pixel_transfer_swap_cleanup_and_fail_closed_call_flow(self):
        with tempfile.TemporaryDirectory(prefix='n00-handoff-host-') as temporary:
            binary = str(Path(temporary) / 'handoff')
            subprocess.run(['cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                            str(SCRIPTS / 'compositor-handoff-guest.c'),
                            str(SCRIPTS / 'tests/compositor-handoff-host.c'), '-o', binary], check=True)
            for mode in range(9):
                with self.subTest(mode=mode):
                    self.assertEqual(subprocess.run([binary, str(mode)], timeout=5).returncode,
                                     0 if mode in (0, 1, 8) else 126)

    def test_incompatible_interactive_settings_fail_before_runtime_setup(self):
        for env in ({'HARMATTAN_UI_HANDOFF': 'bad'},
                    {'HARMATTAN_UI_HANDOFF': 'on', 'HARMATTAN_UI_SPLASH': 'on'},
                    {'HARMATTAN_UI_HANDOFF': 'on', 'HARMATTAN_UI_ANIMATIONS': 'off'}):
            with self.subTest(env=env):
                result = subprocess.run(['sh', str(SCRIPTS / 'run-arm64-ui.sh')],
                                        env={**os.environ, **env}, capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 2)
                self.assertNotIn(b'Native UI run artifacts:', result.stdout)

    def test_unvalidated_splash_combination_rejected(self):
        for values in ({'handoff': 'on'}, {'splash': True, 'handoff': True}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                ANIMATIONS.prepare(**values)


if __name__ == '__main__':
    unittest.main()
