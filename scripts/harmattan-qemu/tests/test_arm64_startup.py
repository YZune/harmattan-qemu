import importlib.util
from pathlib import Path
import unittest

SCRIPTS = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('startup', SCRIPTS / 'arm64-startup.py')
STARTUP = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STARTUP)


def log(released=False):
    # Synthetic state-machine fixture, not real touchscreen evidence.
    value = (b'N00_STARTUP_INPUT_HELD pid=123\n'
             b'N00_STARTUP_INPUT_CHECK tag=home pid=123 buttons=0 keys=0 motions=0\n'
             b'N00_STARTUP_INPUT_CHECK tag=settled pid=123 buttons=4 keys=0 motions=2\n'
             b'N00_STARTUP_INPUT_CHECK tag=final pid=123 buttons=4 keys=0 motions=2\n')
    if released:
        value += (b'N00_STARTUP_INPUT_RELEASE_REQUEST pid=123\n'
                  b'N00_STARTUP_INPUT_RELEASED pid=123 buttons=4 keys=0 motions=2\n')
    return value


class StartupTests(unittest.TestCase):
    def test_held_then_released_after_real_input(self):
        self.assertFalse(STARTUP.validate(log(), exercised=True)['released'])
        self.assertTrue(STARTUP.validate(log(True), released=True, exercised=True)['released'])
        self.assertEqual(STARTUP.validate(log())['early_button_events'], 4)

    def test_early_missing_duplicate_or_changed_guard_fails(self):
        for bad in (b'', log(True), log() + b'unknown warning\n', log().replace(b'HELD', b'FAILED'),
                    log().replace(b'tag=settled', b'tag=home'), log().replace(b'pid=123', b'pid=124', 1),
                    log().replace(b'tag=final pid=123 buttons=4', b'tag=final pid=123 buttons=0')):
            with self.subTest(log=bad), self.assertRaises(ValueError):
                STARTUP.validate(bad)

    def test_unexercised_guard_is_not_real_input_acceptance(self):
        with self.assertRaises(ValueError):
            STARTUP.validate(log().replace(b'buttons=4', b'buttons=0'), exercised=True)

    def test_release_must_be_unique_acknowledged_same_process(self):
        for bad in (log(), log(True) + log(True), log(True).replace(b'RELEASED', b'FAILED'),
                    log(True).replace(b'RELEASE_REQUEST', b'ignored'),
                    log(True).replace(b'RELEASED pid=123', b'RELEASED pid=124')):
            with self.subTest(log=bad), self.assertRaises(ValueError):
                STARTUP.validate(bad, released=True)

    def test_controller_releases_only_after_full_startup_checks(self):
        source = (SCRIPTS / 'diagnose-arm64-shell.py').read_text()
        start = source.index('            if args.interactive:\n')
        interactive = source[start:source.index('            # quit joins', start)]
        release = interactive.index('release=True')
        self.assertLess(interactive.index('validate_desktop_serial'), release)
        self.assertLess(interactive.index('validate_host'), release)
        self.assertLess(interactive.index("not home_frames['content_equal']"), release)
        self.assertGreater(interactive.index("print(f'READY:"), release)


if __name__ == '__main__':
    unittest.main()
