"""Narrow original-compositor target correction; GPU gates remain independent."""
import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('animations_fbo', SCRIPTS / 'arm64-animations.py')
ANIMATIONS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ANIMATIONS)
READY = b'N00_COMPOSITOR_FBO_TARGET_GUARD_READY'
FIXED = b'N00_COMPOSITOR_FBO_TARGET_FIXED site=init+0x74'
IDENTITY = b'N00_COMPOSITOR_FBO_LIBRARY_SHA256 ' + ANIMATIONS.LIBRARY_SHA256.encode() + b'\n'


def report(lines=()):
    return b'\nN00_ANIMATIONS_BEGIN\n' + b'\n'.join(lines) + b'\nN00_ANIMATIONS_END\n'


class CompositorFBOTests(unittest.TestCase):
    def test_actual_shim_correction_exclusions_and_fail_closed_abi(self):
        with tempfile.TemporaryDirectory(prefix='compositor-fbo-') as tmp:
            binary = str(Path(tmp) / 'host')
            subprocess.run(['cc', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror',
                            str(SCRIPTS / 'tests/compositor-fbo-host.c'), '-o', binary], check=True)
            for mode in range(8):
                with self.subTest(mode=mode):
                    run = subprocess.run([binary, str(mode)], capture_output=True, timeout=5)
                    self.assertEqual(run.returncode, 0 if mode == 0 else 123)
                    if mode == 0:
                        self.assertEqual(run.stdout, READY + b'\n' + FIXED + b'\nPASS\n')
                        self.assertEqual(run.stderr, b'')
                    else:
                        self.assertEqual(run.stdout, b'')
                        self.assertEqual(run.stderr, b'N00_COMPOSITOR_FBO_TARGET_ERROR unsupported ABI\n')

    def test_runtime_identity_and_callsite_history(self):
        startup = IDENTITY + report()
        self.assertFalse(ANIMATIONS.validate_fbo_correction(startup)['callsite_fix_observed'])
        observed = startup + report([READY, FIXED])
        self.assertTrue(ANIMATIONS.validate_fbo_correction(observed)['callsite_fix_observed'])
        for invalid in (observed.replace(ANIMATIONS.LIBRARY_SHA256.encode(), b'0' * 64),
                        observed + IDENTITY, report([READY, FIXED]),
                        IDENTITY + report([FIXED]), IDENTITY + report([READY, READY]),
                        observed + report(), observed + b'N00_COMPOSITOR_FBO_TARGET_ERROR',
                        observed.replace(b'init+0x74', b'init+0x78')):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                ANIMATIONS.validate_fbo_correction(invalid)

    def test_explicit_build_variant_and_unchanged_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / 'compositor-guest'
            folder.mkdir()
            elf = b'\x7fELF\x01\x01\x01' + b'\x00' * 9 + b'\x03\x00\x28\x00' + b'\x00' * 32
            for name in ('handoff', 'handoff-fbo'):
                (folder / f'n00-compositor-{name}.so').write_bytes(elf)
            with patch.dict(os.environ, {'HARMATTAN_PORT_WORKSPACE': tmp}, clear=True), \
                    patch.object(ANIMATIONS.subprocess, 'run') as run:
                _, ordinary = ANIMATIONS.prepare(handoff=True)
                self.assertEqual(run.call_args.args[0][-1], '--handoff')
                self.assertNotIn('fbo_target_correction', ordinary)
                _, opted = ANIMATIONS.prepare(handoff=True, fbo=True)
                self.assertEqual(run.call_args.args[0][-1], '--handoff-fbo')
                self.assertEqual(opted['fbo_target_correction']['original_library_sha256'], ANIMATIONS.LIBRARY_SHA256)
        for options in ({'fbo': True}, {'fbo': True, 'handoff': True, 'splash': True},
                        {'fbo': 'on', 'handoff': True}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                ANIMATIONS.prepare(**options)

    def test_guest_full_sha_check_precedes_preload_and_fails_closed(self):
        source = (SCRIPTS / 'diagnose-shell-guest.sh').read_text()
        start = source.index('                perl -MDigest::SHA -e ')
        end = source.index("\n                '\n", start) + len("\n                '")
        snippet = source[start:end]
        self.assertLess(start, source.index('su user -c "$user_env $compositor_env mcompositor'))
        if not shutil.which('perl'):
            self.fail('compositor tests require Perl')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'original-library'
            path.write_bytes(b'controlled original fixture')
            command = snippet.replace(ANIMATIONS.LIBRARY, str(path))
            bad = subprocess.run(['sh', '-ec', command], capture_output=True)
            self.assertNotEqual(bad.returncode, 0)
            self.assertIn(b'library SHA256 mismatch', bad.stderr)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            good = subprocess.run(['sh', '-ec', command.replace(ANIMATIONS.LIBRARY_SHA256, digest)], capture_output=True)
            self.assertEqual(good.returncode, 0, good.stderr)
            self.assertEqual(good.stdout, b'N00_COMPOSITOR_FBO_LIBRARY_SHA256 ' + digest.encode() + b'\n')

    def test_controller_rejects_incompatible_modes_before_building(self):
        import contextlib
        import io
        import sys
        import test_linux_ui as linux_ui
        shell = linux_ui.SHELL
        base = ['diagnose-arm64-shell.py', '--output', '/tmp/unused-compositor-fbo-output',
                '--interactive', '--system-ui', 'on', '--input-method', 'off',
                '--clock', 'off', '--device-orientation', 'disabled',
                '--compositor-animations', 'on', '--display-handoff', 'on', '--splash', 'off']
        for linux, flag, changed in ((False, True, None), (True, True, '--display-handoff'),
                                    (True, True, '--compositor-animations'), (True, True, '--splash'),
                                    (True, True, None), (False, False, None)):
            argv = base.copy()
            if changed:
                argv[argv.index(changed) + 1] = 'on' if changed == '--splash' else 'off'
            if flag:
                argv.append('--compositor-fbo-fix')
            argv += ['--', 'qemu', '-snapshot']
            allowed = changed is None and (linux or not flag)
            with self.subTest(linux=linux, flag=flag, changed=changed), \
                    patch.object(sys, 'argv', argv), patch.dict(os.environ, {}, clear=True), \
                    patch.object(shell, 'validate_host_configuration', return_value=linux), \
                    patch.object(shell.animations, 'prepare', side_effect=RuntimeError('build boundary')) as build, \
                    contextlib.redirect_stderr(io.StringIO()):
                if allowed:
                    with self.assertRaisesRegex(RuntimeError, 'build boundary'):
                        shell.main()
                    build.assert_called_once_with(splash=False, handoff=True, fbo=flag)
                else:
                    with self.assertRaises(SystemExit) as error:
                        shell.main()
                    self.assertEqual(error.exception.code, 2)
                    build.assert_not_called()

    def test_linux_prepare_routes_only_explicit_flag_to_new_variant(self):
        import test_linux_ui as linux_ui
        launcher = linux_ui.LAUNCHER
        for enabled in (False, True):
            with self.subTest(enabled=enabled), tempfile.TemporaryDirectory() as tmp:
                args, prepared = linux_ui.LinuxLauncherTests().fixture(Path(tmp))
                args += ['--prepare-only'] + (['--compositor-fbo-fix'] if enabled else [])
                digest = hashlib.sha256((prepared / 'zImage-2.6.32.26-qemu').read_bytes()).hexdigest()
                with patch.dict(os.environ, {}, clear=True), patch.object(launcher.sys, 'platform', 'linux'), \
                        patch.object(launcher, 'KERNEL_SHA256', digest), \
                        patch.object(launcher.linux_offscreen, 'require_pillow'), \
                        patch.object(launcher.subprocess, 'run') as build:
                    self.assertEqual(launcher.main(args), 0)
                command = build.call_args_list[1].args[0]
                self.assertEqual(command[-1], '--handoff-fbo' if enabled else '--handoff')
