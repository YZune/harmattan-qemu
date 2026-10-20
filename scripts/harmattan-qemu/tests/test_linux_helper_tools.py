"""Host-only tool discovery checks; no helper compilation or guest execution."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import test_linux_ui as linux_ui

LAUNCHER = linux_ui.LAUNCHER


class LinuxHelperToolTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.workspace = self.root / 'helpers'
        self.tools = self.root / 'tools with spaces'
        self.tools.mkdir()

    def executable(self, name):
        path = self.tools / name
        path.write_text('synthetic executable fixture; never run\n')
        path.chmod(0o700)
        return path

    def cache(self, workspace=None):
        workspace = workspace or self.workspace
        for helper, names in LAUNCHER.HELPER_LINK_INPUTS.items():
            directory = workspace / helper / 'link-inputs'
            directory.mkdir(parents=True, exist_ok=True)
            for name in names:
                (directory / name).write_bytes(b'synthetic cache, not hash validation')

    def test_cache_inventory_matches_the_original_builders(self):
        for helper, script in (('orientation-guest', 'build-orientation-guest.sh'),
                               ('compositor-guest', 'build-compositor-guest.sh')):
            source = (linux_ui.SCRIPTS / script).read_text()
            extracted = re.findall(r'^extract_input (\S+) ', source, re.M)
            self.assertEqual(tuple(extracted), LAUNCHER.HELPER_LINK_INPUTS[helper])

    def test_defaults_and_empty_overrides_use_path_without_running_tools(self):
        self.executable('clang')
        self.executable('debugfs')
        for overrides in ({}, {'HARMATTAN_ARMEL_CLANG': '', 'HARMATTAN_DEBUGFS': ''}):
            with self.subTest(overrides=overrides), \
                    patch.dict(os.environ, {'PATH': str(self.tools), **overrides}, clear=True), \
                    patch.object(LAUNCHER.subprocess, 'run') as execute:
                before = dict(os.environ)
                LAUNCHER.require_helper_tools(self.workspace)
                self.assertEqual(dict(os.environ), before)
                execute.assert_not_called()
        self.assertFalse(self.workspace.exists())

    def test_explicit_paths_spaces_symlinks_and_relative_compiler_are_accepted(self):
        compiler = self.executable('selected clang')
        debugfs = self.executable('selected debugfs')
        alias = self.tools / 'compiler alias'
        alias.symlink_to(compiler)
        for selected in (str(compiler), str(alias), os.path.relpath(compiler)):
            with self.subTest(selected=selected), patch.dict(os.environ, {
                    'PATH': '', 'HARMATTAN_ARMEL_CLANG': selected,
                    'HARMATTAN_DEBUGFS': str(debugfs)}, clear=True):
                LAUNCHER.require_helper_tools(self.workspace)

    def test_unset_path_uses_the_actual_builder_shell_default(self):
        compiler = self.executable('selected clang')
        debugfs = self.executable('selected debugfs')
        with patch.dict(os.environ, {'HARMATTAN_ARMEL_CLANG': str(compiler),
                                    'HARMATTAN_DEBUGFS': str(debugfs)}, clear=True):
            expected = subprocess.run(['sh', '-c', 'printf "%s" "$PATH"'],
                                      check=True, capture_output=True, text=True).stdout
            with patch.object(LAUNCHER.shutil, 'which', wraps=shutil.which) as discover:
                LAUNCHER.require_helper_tools(self.workspace)
            self.assertEqual([call.kwargs['path'] for call in discover.call_args_list],
                             [expected, expected])
            self.assertNotIn('PATH', os.environ)

    def test_empty_path_finds_default_compiler_in_current_directory(self):
        self.executable('clang')
        self.executable('debugfs')
        with contextlib.chdir(self.tools), patch.dict(os.environ, {'PATH': ''}, clear=True):
            LAUNCHER.require_helper_tools(self.workspace)
            self.assertEqual(os.environ['PATH'], '')

    def test_cwd_dependent_debugfs_selections_are_left_to_original_builders(self):
        compiler = self.executable('selected clang')
        for selected, path in (('../../../tools/debugfs', str(self.tools)),
                               ('debugfs', 'relative-tools'), ('debugfs', ''),
                               ('debugfs', str(self.tools) + ':'),
                               ('debugfs', str(self.tools) + ':relative-tools')):
            environment = {'PATH': path, 'HARMATTAN_ARMEL_CLANG': str(compiler),
                           'HARMATTAN_DEBUGFS': selected}
            with self.subTest(selected=selected, path=path), \
                    patch.dict(os.environ, environment, clear=True), \
                    patch.object(LAUNCHER.subprocess, 'run') as execute:
                LAUNCHER.require_helper_tools(self.workspace)
                self.assertEqual(dict(os.environ), environment)
                execute.assert_not_called()
        self.assertFalse(self.workspace.exists())

    def test_failed_shell_path_probe_is_an_actionable_preflight_failure(self):
        for failure in (FileNotFoundError('sh'), subprocess.TimeoutExpired(['sh'], 5)):
            with self.subTest(failure=type(failure).__name__), \
                    patch.dict(os.environ, {}, clear=True), \
                    patch.object(LAUNCHER.subprocess, 'run', side_effect=failure):
                with self.assertRaisesRegex(ValueError, 'helper shell search path'):
                    LAUNCHER.require_helper_tools(self.workspace)
        self.assertFalse(self.workspace.exists())

    def test_missing_nonexecutable_and_directory_selections_are_rejected(self):
        debugfs = self.executable('debugfs')
        nonexecutable = self.tools / 'not executable'
        nonexecutable.write_text('not a tool')
        for selected in ('missing-clang', str(nonexecutable), str(self.tools)):
            with self.subTest(selected=selected), patch.dict(os.environ, {
                    'PATH': '', 'HARMATTAN_ARMEL_CLANG': selected,
                    'HARMATTAN_DEBUGFS': str(debugfs)}, clear=True):
                with self.assertRaisesRegex(ValueError, 'HARMATTAN_ARMEL_CLANG') as error:
                    LAUNCHER.require_helper_tools(self.workspace)
                self.assertIn(repr(selected), str(error.exception))
                self.assertNotIn('HARMATTAN_DEBUGFS=', str(error.exception))

    def test_missing_required_tools_are_reported_together(self):
        with patch.dict(os.environ, {'PATH': str(self.tools)}, clear=True):
            with self.assertRaises(ValueError) as error:
                LAUNCHER.require_helper_tools(self.workspace)
        self.assertIn("HARMATTAN_ARMEL_CLANG='clang'", str(error.exception))
        self.assertIn("HARMATTAN_DEBUGFS='debugfs'", str(error.exception))
        self.assertIn('docs/linux.md', str(error.exception))
        self.assertFalse(self.workspace.exists())

    def test_complete_cache_does_not_add_a_debugfs_requirement(self):
        self.cache()
        compiler = self.executable('clang')
        with patch.dict(os.environ, {'PATH': str(self.tools), 'HARMATTAN_ARMEL_CLANG': str(compiler),
                                    'HARMATTAN_DEBUGFS': 'missing-debugfs'}, clear=True):
            LAUNCHER.require_helper_tools(self.workspace)
            with self.assertRaisesRegex(ValueError, 'HARMATTAN_DEBUGFS'):
                LAUNCHER.require_helper_tools(self.workspace, exercise_keyboard=True)
        with patch.dict(os.environ, {'PATH': ''}, clear=True):
            with self.assertRaisesRegex(ValueError, 'HARMATTAN_ARMEL_CLANG') as error:
                LAUNCHER.require_helper_tools(self.workspace)
            self.assertNotIn('HARMATTAN_DEBUGFS=', str(error.exception))

    def test_each_missing_cache_input_requires_debugfs_without_changing_cache(self):
        self.cache()
        compiler = self.executable('clang')
        for helper, names in LAUNCHER.HELPER_LINK_INPUTS.items():
            for name in names:
                path = self.workspace / helper / 'link-inputs' / name
                original = path.read_bytes()
                path.unlink()
                with self.subTest(helper=helper, name=name), patch.dict(os.environ, {
                        'PATH': str(self.tools), 'HARMATTAN_ARMEL_CLANG': str(compiler)}, clear=True):
                    with self.assertRaisesRegex(ValueError, 'HARMATTAN_DEBUGFS'):
                        LAUNCHER.require_helper_tools(self.workspace)
                self.assertFalse(path.exists())
                path.write_bytes(original)

    def test_missing_tools_fail_all_modes_before_outputs_or_processes(self):
        compiler = self.executable('clang')
        debugfs = self.executable('debugfs')
        for mode in ('startup', 'usability', 'live', 'prepare-only'):
            for missing in ('HARMATTAN_ARMEL_CLANG', 'HARMATTAN_DEBUGFS'):
                with self.subTest(mode=mode, missing=missing):
                    root = self.root / f'{mode}-{missing}'
                    args, prepared = linux_ui.LinuxLauncherTests().fixture(root)
                    helpers, session, profile = root / 'helpers', root / 'session', root / 'profile'
                    args += ['--helper-workspace', str(helpers)]
                    args += ['--prepare-only'] if mode == 'prepare-only' else ['--mode', mode]
                    if mode == 'live':
                        args += ['--live-session', str(session), '--profile', str(profile)]
                    environment = {'PATH': str(self.tools), 'HARMATTAN_ARMEL_CLANG': str(compiler),
                                   'HARMATTAN_DEBUGFS': str(debugfs)}
                    environment[missing] = 'missing-tool'
                    before = {path.name: path.read_bytes() for path in prepared.iterdir()}
                    digest = hashlib.sha256((prepared / 'zImage-2.6.32.26-qemu').read_bytes()).hexdigest()
                    errors = io.StringIO()
                    with patch.dict(os.environ, environment, clear=True), \
                            patch.object(LAUNCHER.sys, 'platform', 'linux'), \
                            patch.object(LAUNCHER, 'KERNEL_SHA256', digest), \
                            patch.object(LAUNCHER.linux_offscreen, 'require_pillow'), \
                            patch.object(LAUNCHER.subprocess, 'run') as execute, \
                            patch.object(LAUNCHER, 'run_controller') as controller, \
                            patch.object(LAUNCHER.native_supervisor, 'run') as supervisor, \
                            contextlib.redirect_stderr(errors):
                        with self.assertRaises(SystemExit) as error:
                            LAUNCHER.main(args)
                        self.assertEqual(error.exception.code, 2)
                        execute.assert_not_called()
                        controller.assert_not_called()
                        supervisor.assert_not_called()
                    self.assertIn(missing + "='missing-tool'", errors.getvalue())
                    self.assertNotIn('Traceback', errors.getvalue())
                    for path in (root / 'run', helpers, session, profile):
                        self.assertFalse(path.exists(), path)
                    self.assertEqual({path.name: path.read_bytes() for path in prepared.iterdir()}, before)

    def test_valid_tools_preserve_selections_and_continue_to_controller(self):
        compiler = self.executable('selected clang')
        debugfs = self.executable('selected debugfs')
        args, prepared = linux_ui.LinuxLauncherTests().fixture(self.root / 'valid')
        environment = {'PATH': '', 'HARMATTAN_ARMEL_CLANG': str(compiler),
                       'HARMATTAN_DEBUGFS': str(debugfs)}
        observed = []
        def controller(command, env, log, timeout):
            observed.append(env)
            (log.parent / 'ui').mkdir()
            (log.parent / 'ui/startup-result.json').write_text('{"passed": true}')
            return 0
        digest = hashlib.sha256((prepared / 'zImage-2.6.32.26-qemu').read_bytes()).hexdigest()
        with patch.dict(os.environ, environment, clear=True), \
                patch.object(LAUNCHER.sys, 'platform', 'linux'), \
                patch.object(LAUNCHER, 'KERNEL_SHA256', digest), \
                patch.object(LAUNCHER.linux_offscreen, 'require_pillow'), \
                patch.object(LAUNCHER.subprocess, 'run'), \
                patch.object(LAUNCHER, 'run_controller', side_effect=controller), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(LAUNCHER.main(args), 0)
        self.assertEqual({key: observed[0][key] for key in environment}, environment)
        record = json.loads((self.root / 'valid/run/launch-result.json').read_text())
        self.assertTrue(record['passed'])

    def test_cached_main_requires_debugfs_only_for_keyboard_extraction_modes(self):
        compiler = self.executable('clang')
        for mode in ('startup', 'live', 'usability', 'prepare-only'):
            with self.subTest(mode=mode):
                root = self.root / f'cached-{mode}'
                args, prepared = linux_ui.LinuxLauncherTests().fixture(root)
                helpers = root / 'helpers'
                self.cache(helpers)
                args += ['--helper-workspace', str(helpers)]
                args += ['--prepare-only'] if mode == 'prepare-only' else ['--mode', mode]
                if mode == 'live':
                    args += ['--live-session', str(root / 'session')]
                def controller(command, env, log, timeout):
                    (log.parent / 'ui').mkdir()
                    (log.parent / 'ui/startup-result.json').write_text('{"passed": true}')
                    return 0
                digest = hashlib.sha256((prepared / 'zImage-2.6.32.26-qemu').read_bytes()).hexdigest()
                with patch.dict(os.environ, {'PATH': str(self.tools), 'HARMATTAN_ARMEL_CLANG': str(compiler),
                                            'HARMATTAN_DEBUGFS': 'missing-debugfs'}, clear=True), \
                        patch.object(LAUNCHER.sys, 'platform', 'linux'), \
                        patch.object(LAUNCHER, 'KERNEL_SHA256', digest), \
                        patch.object(LAUNCHER.linux_offscreen, 'require_pillow'), \
                        patch.object(LAUNCHER.subprocess, 'run') as execute, \
                        patch.object(LAUNCHER, 'run_controller', side_effect=controller) as run, \
                        contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    if mode in ('startup', 'live'):
                        self.assertEqual(LAUNCHER.main(args), 0)
                        run.assert_called_once()
                    else:
                        with self.assertRaises(SystemExit) as error:
                            LAUNCHER.main(args)
                        self.assertEqual(error.exception.code, 2)
                        execute.assert_not_called()
                        run.assert_not_called()
                        self.assertFalse((root / 'run').exists())


if __name__ == '__main__':
    unittest.main()
