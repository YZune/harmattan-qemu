"""Guard experimental scope and reject incomplete/stale acceptance evidence."""
import array
import importlib.util
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location('call_simulation', ROOT / 'scripts/harmattan-qemu/arm64-call-simulation.py')
calls = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(calls)


class CallSimulationTests(unittest.TestCase):
    def test_explicit_scope(self):
        valid = dict(interactive=True, ready=True, profile=None, rotation=270, test=False)
        calls.validate_configuration('on', **valid)
        for changed in ({'interactive': False}, {'ready': False}, {'profile': Path('/private/profile')}, {'rotation': 90}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                calls.validate_configuration('on', **(valid | changed))
        with self.assertRaises(ValueError):
            calls.validate_configuration('off', **(valid | {'test': True}))
        with self.assertRaises(ValueError):
            calls.validate_configuration('fake', **valid)

    def report(self):
        helper = 'a' * 32
        return (f'N00_CALL_BACKEND_PID 42\nN00_CALL_UI_PID 43\n'
                f'{helper}  /proc/42/exe\n{calls.UI_MD5}  /proc/43/exe\n'
                f'N00_CALL_GCONF_PID 45\n{calls.GCONF_MD5}  /proc/45/exe\n'
                'N00_CALL_STATUS_BEGIN\nmethod return\n   uint32 1\n   uint32 2\n   uint32 1\n'
                'N00_CALL_STATUS_END\nDEMO_STATE incoming sequence=2\n').encode(), {'helper_md5': helper}

    def test_report_pins_original_ui_and_instance(self):
        data, info = self.report()
        self.assertEqual(calls.validate_report(data, info), {'state': 1, 'sequence': 2, 'ringing_audio': True})
        self.assertEqual(info['ui_pid'], 43)
        with self.assertRaises(ValueError):
            calls.validate_report(data.replace(b'43', b'44'), info)

    def test_reject_incomplete_or_failed_evidence(self):
        data, info = self.report()
        for broken in (data + data, data.replace(calls.UI_MD5.encode(), b'b' * 32),
                       data.replace(b'N00_CALL_STATUS_END', b'incomplete'),
                       data.replace(b'uint32 1', b'uint32 8'),
                       data + b'DEMO_TONE_ERROR stream\n', data + b'DEMO_REMOTE_ERROR service\n'):
            with self.subTest(broken=broken[-40:]), self.assertRaises(ValueError):
                calls.validate_report(broken, dict(info))

    def test_locked_report_requires_same_relay_and_clean_transfer(self):
        data, info = self.report()
        info.update(locked=True, relay_md5='c' * 32)
        relay = b'N00_CALL_RELAY_PID 46\n' + b'c' * 32 + b'  /proc/46/exe\n'
        good = data + relay
        self.assertEqual(calls.validate_report(good, info)['state'], 1)
        for bad in (data, good + relay, good.replace(b'46', b'47'),
                    good + b'LOCK_FORWARD_ERROR denied\n', good + b'LOCK_FATAL state\n',
                    good + b'LIVE_FATAL consumer geometry\n'):
            with self.subTest(bad=bad[-60:]), self.assertRaises(ValueError):
                calls.validate_report(bad, dict(info))

    def test_audio_requires_non_silent_tail(self):
        non_silent = array.array('h', [1000, -1000] * (44100 * 6)).tobytes()
        self.assertGreater(calls.validate_ringtone(non_silent)['rms'], 20)
        for data in (b'\0' * len(non_silent), non_silent + b'\0' * (44100 * 4 * 5), non_silent[:-1], b''):
            with self.subTest(length=len(data)), self.assertRaises(ValueError):
                calls.validate_ringtone(data)

    def test_call_gpu_lifetime_preserves_desktop_gate(self):
        import test_arm64_systemui as desktop
        data = desktop.host().replace(b'N00_GLES disconnect client=1',
            b'N00_GLES connect client=4 abi=2\n'
            b'N00_GLES current client=4 es=2 renderer=Apple Test GPU\n'
            b'N00_GLES disconnect client=4\nN00_GLES disconnect client=1')
        self.assertEqual(calls.validate_host(data, desktop.UI.validate_host)['gpu_contexts'], 4)
        with self.assertRaises(ValueError):
            desktop.UI.validate_host(data)
        for bad in (desktop.host(), data.replace(b'client=4 abi=2', b'client=4 abi=1'),
                    data.replace(b'client=4', b'client=5'), data.replace(b'faults=0', b'faults=1'),
                    data.replace(b'rejects=0', b'rejects=1'), data + b'warning\n',
                    data.replace(b'N00_GLES disconnect client=4\n', b''),
                    data.replace(b'N00_GLES connect client=4 abi=2\n', b'N00_GLES connect client=4 abi=2\n' * 2),
                    data.replace(b'N00_GLES disconnect client=4\n', b'N00_GLES disconnect client=1\n')):
            with self.subTest(bad=bad[-70:]), self.assertRaises(ValueError):
                calls.validate_host(bad, desktop.UI.validate_host)

    def test_missing_theme_resources_and_controls_fail(self):
        header = b'P6\n480 864\n255\n'
        for ppm in (b'', header + b'\0' * (480 * 864 * 3),
                    header + bytes((255, 64, 64)) * (480 * 864)):
            with self.assertRaises(ValueError):
                calls.validate_pixels(ppm, 'incoming')
            with self.assertRaises(ValueError):
                calls.validate_locked_pixels(ppm)

    def test_shell_refuses_profile_and_invalid_modes_before_running(self):
        import os
        script = ROOT / 'scripts/harmattan-qemu/run-arm64-ui.sh'
        base = os.environ | {'HARMATTAN_UI_CALL_SIMULATION': 'on'}
        for env, args in ((base | {'HARMATTAN_USER_PROFILE': '/private/profile'}, []),
                          (base | {'HARMATTAN_UI_STARTUP_WAITS': 'fixed'}, []),
                          (base, ['--usability-headless-diagnostic']),
                          (base | {'HARMATTAN_UI_CALL_SIMULATION_TEST': 'on'}, []),
                          (base | {'HARMATTAN_UI_CALL_LOCKSCREEN': 'on', 'HARMATTAN_UI_LOCKSCREEN': 'off'}, []),
                          (base | {'HARMATTAN_UI_CALL_LOCKSCREEN': 'invalid'}, [])):
            with self.subTest(args=args):
                result = subprocess.run(['sh', str(script), *args], env=env, capture_output=True, timeout=5)
                self.assertEqual(result.returncode, 2, result.stderr)


if __name__ == '__main__':
    unittest.main()
