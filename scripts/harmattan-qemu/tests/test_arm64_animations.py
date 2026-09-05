import importlib.util
import hashlib
import itertools
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / 'scripts/harmattan-qemu'
SPEC = importlib.util.spec_from_file_location('animations', SCRIPTS / 'arm64-animations.py')
ANIMATIONS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ANIMATIONS)
MOTION_SPEC = importlib.util.spec_from_file_location('transitions', SCRIPTS / 'probe-arm64-transitions.py')
MOTION = importlib.util.module_from_spec(MOTION_SPEC)
MOTION_SPEC.loader.exec_module(MOTION)
HELPER_MD5 = 'a' * 32


def report():
    # Synthetic validator fixture; not runtime evidence.
    return (f'\nN00_ANIMATIONS_BEGIN\nN00_ANIMATIONS_PID 229\n'
            f'{ANIMATIONS.LIBRARY_MD5}  {ANIMATIONS.LIBRARY}\n'
            f'{HELPER_MD5}  {ANIMATIONS.HELPER}\n'
            f'LD_PRELOAD={ANIMATIONS.HELPER}\n'
            'N00_ANIMATIONS_MAPPED\nN00_COMPOSITOR_WORLD_CACHE_ACTIVE\n'
            'N00_COMPOSITOR_PROJECTION_APPLIED\n'
            'N00_ANIMATIONS_PROCESS_SCOPE_OK\nN00_ANIMATIONS_END\n').encode()


class AnimationTests(unittest.TestCase):
    def test_transition_inspection_passes_clock_stage_to_guest(self):
        with tempfile.TemporaryDirectory() as directory:
            serial = mock.Mock()
            framebuffer = mock.Mock()
            framebuffer.FrameProbe.return_value.registers = {}
            with mock.patch.object(MOTION.time, 'monotonic', side_effect=itertools.count(0,100)):
                MOTION.run_probe(mock.Mock(), serial, mock.Mock(), mock.Mock(), mock.Mock(),
                                 270, Path(directory), mock.Mock(), framebuffer)
            commands = b''.join(call.args[0] for call in serial.sendall.call_args_list)
            for stage in ('before','opened','sum','returned','reopened','final'):
                self.assertIn(f'calculator-inspect {stage};'.encode(), commands)

    def test_splash_build_is_a_separate_opt_in_artifact(self):
        with tempfile.TemporaryDirectory(prefix='n00-compositor-select-') as temporary:
            directory = Path(temporary) / 'compositor-guest'
            directory.mkdir()
            elf = bytearray(64)
            elf[:7] = b'\x7fELF\x01\x01\x01'
            elf[16:20] = b'\x03\x00\x28\x00'
            for variant, value in (('matrices', 1), ('splash', 2), ('handoff', 3)):
                elf[-1] = value
                (directory / f'n00-compositor-{variant}.so').write_bytes(elf)
            with mock.patch.dict(ANIMATIONS.os.environ, {'HARMATTAN_PORT_WORKSPACE': temporary}), \
                 mock.patch.object(ANIMATIONS.subprocess, 'run') as build:
                binary, info = ANIMATIONS.prepare()
                self.assertEqual(binary[-1], 1)
                self.assertFalse(info['splash_repairs'])
                self.assertFalse(info['display_handoff'])
                self.assertNotIn('splash_source_sha256', info)
                self.assertEqual(build.call_args.args[0], ['sh', str(SCRIPTS / 'build-compositor-guest.sh')])
                binary, info = ANIMATIONS.prepare(splash=True)
                self.assertEqual(binary[-1], 2)
                self.assertTrue(info['splash_repairs'])
                self.assertEqual(info['splash_source_sha256'], hashlib.sha256((SCRIPTS / 'compositor-splash-guest.c').read_bytes()).hexdigest())
                self.assertEqual(build.call_args.args[0][-1], '--splash')
                binary, info = ANIMATIONS.prepare(handoff=True)
                self.assertEqual(binary[-1], 3)
                self.assertTrue(info['display_handoff'])
                self.assertFalse(info['splash_repairs'])
                self.assertEqual(info['handoff_source_sha256'], hashlib.sha256((SCRIPTS / 'compositor-handoff-guest.c').read_bytes()).hexdigest())
                self.assertEqual(build.call_args.args[0][-1], '--handoff')
                with self.assertRaises(ValueError):
                    ANIMATIONS.prepare(splash='on')

    def test_defaults_preserve_historical_profiles(self):
        self.assertTrue(ANIMATIONS.enabled(None, True))
        self.assertFalse(ANIMATIONS.enabled(None, False))
        self.assertFalse(ANIMATIONS.enabled('off', True))
        self.assertTrue(ANIMATIONS.enabled('on', False))
        with self.assertRaises(ValueError):
            ANIMATIONS.enabled('invalid', True)

    def test_original_library_and_runtime_activation(self):
        result = ANIMATIONS.validate_serial(report() * 3, HELPER_MD5)
        self.assertEqual(result['pid'], 229)
        self.assertTrue(result['projection_initialized'])
        self.assertIn('activation only', result['scope'])

    def test_missing_replaced_unscoped_or_restarted_helper_fails(self):
        good = report() * 3
        for old, new in ((ANIMATIONS.LIBRARY_MD5.encode(), b'0' * 32),
                         (HELPER_MD5.encode(), b'0' * 32),
                         (b'LD_PRELOAD=', b'NOT_PRELOAD='),
                         (b'N00_ANIMATIONS_MAPPED', b''),
                         (b'N00_COMPOSITOR_WORLD_CACHE_ACTIVE', b''),
                         (b'N00_COMPOSITOR_PROJECTION_APPLIED', b''),
                         (b'N00_ANIMATIONS_PROCESS_SCOPE_OK', b''),
                         (b'N00_ANIMATIONS_END', b'')):
            with self.subTest(old=old), self.assertRaises(ValueError):
                ANIMATIONS.validate_serial(good.replace(old, new), HELPER_MD5)
        for bad in (report(), good + b'\nN00_ANIMATIONS_BEGIN\n',
                    good.replace(b'PID 229', b'PID 230', 1),
                    good.replace(b'N00_ANIMATIONS_MAPPED', b'N00_ANIMATIONS_MAPPED\nN00_COMPOSITOR_MATRICES_ERROR')):
            with self.assertRaises(ValueError):
                ANIMATIONS.validate_serial(bad, HELPER_MD5)

    def test_guest_helper_abi_matrix_and_binding_restore(self):
        with tempfile.TemporaryDirectory(prefix='harmattan-matrices-') as temporary:
            binary = str(Path(temporary) / 'test-matrices')
            subprocess.run(['cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                            str(SCRIPTS / 'compositor-matrices-guest.c'),
                            str(SCRIPTS / 'tests/compositor-matrices-host.c'), '-o', binary], check=True)
            for mode in range(7):
                with self.subTest(mode=mode):
                    result = subprocess.run([binary, str(mode)], timeout=5)
                    self.assertEqual(result.returncode, 0 if mode < 3 else 122)

    def test_root_resize_does_not_enter_child_stacking(self):
        with tempfile.TemporaryDirectory(prefix='harmattan-restacker-') as temporary:
            binary = str(Path(temporary) / 'test-restacker')
            subprocess.run(['cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                            str(SCRIPTS / 'compositor-restacker-guest.c'),
                            str(SCRIPTS / 'tests/compositor-restacker-host.c'), '-o', binary], check=True)
            for mode in range(3):
                result = subprocess.run([binary, str(mode)], timeout=5, capture_output=True)
                self.assertEqual(result.returncode, 0 if mode == 0 else 127)
        guarded = report().replace(b'N00_ANIMATIONS_MAPPED',
            b'N00_ANIMATIONS_MAPPED\nN00_COMPOSITOR_ROOT_CONFIGURE_IGNORED')
        self.assertTrue(ANIMATIONS.validate_serial(guarded*3, HELPER_MD5,
            require_root_guard=True)['root_configure_guard_observed'])
        with self.assertRaises(ValueError):
            ANIMATIONS.validate_serial(report()*3, HELPER_MD5, require_root_guard=True)

    def test_invalid_pixmap_keeps_texture_and_valid_backing_resumes_original_update(self):
        with tempfile.TemporaryDirectory(prefix='harmattan-pixmap-') as temporary:
            binary = str(Path(temporary) / 'test-pixmap')
            subprocess.run(['cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                            str(SCRIPTS / 'compositor-pixmap-guest.c'),
                            str(SCRIPTS / 'tests/compositor-pixmap-host.c'), '-o', binary], check=True)
            for mode in range(3):
                result = subprocess.run([binary, str(mode)], timeout=5, capture_output=True)
                self.assertEqual(result.returncode, 0 if mode == 0 else 128)

    def test_motion_frames_and_black_flashes_are_independent(self):
        # Full-colour synthetic images exercise the classifier, not a real UI.
        home, zero, five = (bytes([n]) * (864 * 480 * 3) for n in (10, 20, 30))
        images = {f'{n}.ppm': MOTION.HEADER + bytes([n]) * len(home) for n in (40, 50, 60)}
        samples = []
        for stage in MOTION.STAGES:
            for n in range(10):
                record = {'stage': stage, 'end': len(samples) + 1,
                          'rgb_sha256': hashlib.sha256(home).hexdigest()}
                if n < 3:
                    name = f'{40 + n * 10}.ppm'
                    record.update(frame=name, rgb_sha256=hashlib.sha256(MOTION.rgb(images[name])).hexdigest())
                samples.append(record)
        result = MOTION.summarize(samples, images, home, zero, five)
        self.assertTrue(result['motion_frames_present'])
        self.assertTrue(result['black_flash_eliminated_in_samples'])
        samples[4]['rgb_sha256'] = MOTION.BLACK
        result = MOTION.summarize(samples, images, home, zero, five)
        self.assertTrue(result['motion_frames_present'])
        self.assertFalse(result['black_flash_eliminated_in_samples'])
        self.assertEqual(result['stages']['open']['black_samples'], 1)
        with self.assertRaises(ValueError):
            MOTION.summarize(list(reversed(samples)), images, home, zero, five)
        with self.assertRaises(ValueError):
            MOTION.summarize(samples, {**images, '40.ppm': images['50.ppm']}, home, zero, five)

    def test_scrollbar_sized_changes_are_not_animation_acceptance(self):
        home = bytes([10]) * (864 * 480 * 3)
        changed = bytes([20]) * 2000 * 3 + home[6000:]
        image = MOTION.HEADER + changed
        samples = [{'stage': stage, 'end': i * 10 + j + 1,
                    'rgb_sha256': hashlib.sha256(changed).hexdigest(), 'frame': 'scrollbar.ppm'}
                   for i, stage in enumerate(MOTION.STAGES) for j in range(10)]
        result = MOTION.summarize(samples, {'scrollbar.ppm': image}, home, home, home)
        self.assertFalse(result['motion_frames_present'])


if __name__ == '__main__':
    unittest.main()
