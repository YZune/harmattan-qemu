"""Source-build discovery only: synthetic tools are never executed."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    'linux_build_environment', Path(__file__).resolve().parents[2] / 'check-environment.py')
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class LinuxBuildEnvironmentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.tools = self.root / 'tools with spaces'
        self.tools.mkdir()
        for name in ('sh', 'git', 'make', 'tar', 'shasum', 'file', 'cc',
                     'ninja', 'python3', 'pkg-config', 'clang', 'debugfs'):
            self.executable(name)
        self.manifest = {'inputs': [
            {'id': 'qemu-source', 'group': 'source', 'path': 'sources/qemu.tar.xz',
             'environment': 'HARMATTAN_QEMU_TARBALL'},
            {'id': 'dgles-source', 'group': 'source', 'path': 'sources/dgles.tar.gz',
             'environment': 'HARMATTAN_GLES_TARBALL'},
            {'id': 'guest-kernel', 'group': 'guest', 'path': 'guest/kernel',
             'environment': 'HARMATTAN_KERNEL'},
            {'id': 'optional-artwork', 'group': 'guest', 'path': 'guest/artwork',
             'optional': True},
        ]}
        (self.root / 'docs').mkdir()
        (self.root / 'docs/inputs.json').write_text(json.dumps(self.manifest))
        (self.root / 'sources').mkdir()
        for item in self.manifest['inputs'][:2]:
            (self.root / item['path']).write_bytes(b'synthetic presence fixture, not an archive')

    def executable(self, name, directory=None):
        path = (directory or self.tools) / name
        path.write_text('synthetic executable fixture; never run\n')
        path.chmod(0o700)
        return path

    def invoke(self, args=('--linux-build',), *, env=None, system='Linux', machine='x86_64',
               version=(3, 12), package_results=None, shell_path=None):
        environment = {'PATH': str(self.tools)} if env is None else env
        package_results = package_results or {}

        def execute(command, **kwargs):
            if command == ['sh', '-c', 'printf "%s" "$PATH"']:
                if isinstance(shell_path, Exception):
                    raise shell_path
                self.assertIsNotNone(shell_path, 'unexpected shell execution')
                self.assertEqual(kwargs['timeout'], 5)
                return subprocess.CompletedProcess(command, 0, stdout=shell_path)
            self.assertEqual(len(command), 3)
            self.assertEqual(command[1], '--exists')
            self.assertIn(command[2], ('glib-2.0', 'pixman-1', 'slirp'))
            result = package_results.get(command[2], 0)
            if isinstance(result, Exception):
                raise result
            return subprocess.CompletedProcess(command, result)

        stdout = io.StringIO()
        with patch.object(CHECK, 'ROOT', self.root), \
                patch.dict(os.environ, environment, clear=True), \
                patch.object(CHECK.platform, 'system', return_value=system), \
                patch.object(CHECK.platform, 'machine', return_value=machine), \
                patch.object(CHECK.platform, 'python_version', return_value='.'.join(map(str, version))), \
                patch.object(CHECK.sys, 'version_info', version), \
                patch.object(CHECK.subprocess, 'run', side_effect=execute) as run, \
                contextlib.redirect_stdout(stdout):
            before = dict(os.environ)
            result = CHECK.main(list(args))
            self.assertEqual(dict(os.environ), before)
        return result, stdout.getvalue(), run

    def test_defaults_and_empty_overrides_use_builder_defaults(self):
        keys = ('HARMATTAN_CC', 'HARMATTAN_NINJA', 'HARMATTAN_PYTHON',
                'HARMATTAN_QEMU_TARBALL', 'HARMATTAN_GLES_TARBALL')
        for overrides in ({}, dict.fromkeys(keys, '')):
            with self.subTest(overrides=overrides):
                result, output, run = self.invoke(env={'PATH': str(self.tools), **overrides})
                self.assertEqual(result, 0, output)
                self.assertIn("DGLES compiler (HARMATTAN_CC): 'cc'", output)
                self.assertIn("Ninja (HARMATTAN_NINJA): 'ninja'", output)
                self.assertIn("QEMU Python (HARMATTAN_PYTHON): 'python3'", output)
                self.assertEqual(run.call_count, 3)
                self.assertIn('does not verify the selected Python version', output)
                self.assertIn('HARMATTAN_CC selects DGLES only', output)

    def test_explicit_paths_spaces_and_symlinks_are_discovered_not_executed(self):
        compiler = self.executable('selected compiler')
        python = self.executable('selected python')
        ninja = self.executable('selected ninja')
        alias = self.tools / 'compiler alias'
        alias.symlink_to(compiler)
        for selected in (compiler, alias, Path(os.path.relpath(compiler))):
            with self.subTest(selected=selected):
                result, output, run = self.invoke(env={
                    'PATH': str(self.tools), 'HARMATTAN_CC': str(selected),
                    'HARMATTAN_PYTHON': str(python), 'HARMATTAN_NINJA': str(ninja)})
                self.assertEqual(result, 0, output)
                self.assertIn(repr(str(selected)), output)
                self.assertEqual([call.args[0] for call in run.call_args_list], [
                    [str(self.tools / 'pkg-config'), '--exists', package]
                    for package in ('glib-2.0', 'pixman-1', 'slirp')])

    def test_missing_nonexecutable_directory_and_command_strings_fail_discovery(self):
        nonexecutable = self.tools / 'nonexecutable'
        nonexecutable.write_text('not executable')
        for key in ('HARMATTAN_CC', 'HARMATTAN_NINJA', 'HARMATTAN_PYTHON'):
            for selected in ('missing-tool', str(nonexecutable), str(self.tools), 'cc -O2'):
                with self.subTest(key=key, selected=selected):
                    result, output, _ = self.invoke(env={'PATH': str(self.tools), key: selected})
                    self.assertEqual(result, 1)
                    line = next(line for line in output.splitlines() if f'({key})' in line)
                    self.assertTrue(line.startswith('MISSING:'), line)
                    self.assertIn(repr(selected), line)

    def test_each_direct_build_tool_is_required(self):
        for name in ('sh', 'git', 'make', 'tar', 'shasum', 'file'):
            with self.subTest(tool=name):
                tool = self.tools / name
                tool.chmod(0o600)
                try:
                    result, output, _ = self.invoke()
                    self.assertEqual(result, 1)
                    self.assertIn(f'MISSING: {name}:', output)
                finally:
                    tool.chmod(0o700)

    def test_missing_pkg_config_does_not_execute_queries(self):
        (self.tools / 'pkg-config').unlink()
        result, output, run = self.invoke()
        self.assertEqual(result, 1)
        run.assert_not_called()
        self.assertIn('MISSING: QEMU pkg-config:', output)
        for package in ('glib-2.0', 'pixman-1', 'slirp'):
            self.assertIn(f'MISSING: {package}:', output)

    def test_failed_erroring_and_timed_out_pkg_config_are_actionable_failures(self):
        failures = (1, FileNotFoundError('pkg-config vanished'),
                    PermissionError('pkg-config denied'), subprocess.TimeoutExpired(['pkg-config'], 5))
        for failure in failures:
            with self.subTest(failure=repr(failure)):
                result, output, run = self.invoke(package_results={'pixman-1': failure})
                self.assertEqual(result, 1)
                self.assertIn('MISSING: pixman-1:', output)
                self.assertIn('OK: glib-2.0:', output)
                self.assertIn('OK: slirp:', output)
                self.assertNotIn('Traceback', output)
                self.assertEqual(run.call_count, 3)

    def test_queries_are_bounded_and_preserve_private_dependency_environment(self):
        environment = {'PATH': str(self.tools), 'PKG_CONFIG_PATH': '/private/dependencies',
                       'LD_LIBRARY_PATH': '/private/libraries', 'CC': 'selected-qemu-compiler'}
        result, output, run = self.invoke(env=environment)
        self.assertEqual(result, 0, output)
        for call in run.call_args_list:
            self.assertEqual(call.kwargs, {
                'check': False, 'env': {**environment, 'PATH': f'{self.tools}:{self.tools}'},
                'timeout': 5, 'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL})
        self.assertNotIn('MISSING: osmesa', output)
        self.assertNotIn('DTC', output)

    def test_ninja_directory_prefix_selects_qemu_tools_not_dgles_compiler(self):
        selected = self.root / 'selected ninja directory'
        selected.mkdir()
        ninja = self.executable('ninja', selected)
        python = self.executable('python3', selected)
        pkg_config = self.executable('pkg-config', selected)
        self.executable('cc', selected)
        result, output, run = self.invoke(env={'PATH': str(self.tools), 'HARMATTAN_NINJA': str(ninja)})
        self.assertEqual(result, 0, output)
        self.assertIn(f"DGLES compiler (HARMATTAN_CC): 'cc' -> {self.tools / 'cc'}", output)
        self.assertIn(f"QEMU Python (HARMATTAN_PYTHON): 'python3' -> {python}", output)
        for call in run.call_args_list:
            self.assertEqual(call.args[0][0], str(pkg_config))
            self.assertEqual(call.kwargs['env']['PATH'], f'{selected}:{self.tools}')

    def test_ninja_symlink_uses_alias_directory_not_target_directory(self):
        aliases = self.root / 'aliases'
        aliases.mkdir()
        alias = aliases / 'ninja'
        alias.symlink_to(self.tools / 'ninja')
        pkg_config = self.executable('pkg-config', aliases)
        result, output, run = self.invoke(env={'PATH': str(self.tools), 'HARMATTAN_NINJA': str(alias)})
        self.assertEqual(result, 0, output)
        self.assertEqual(run.call_args_list[0].args[0][0], str(pkg_config))
        self.assertEqual(run.call_args_list[0].kwargs['env']['PATH'], f'{aliases}:{self.tools}')

    def test_unset_path_uses_shell_default_without_modifying_environment(self):
        result, output, run = self.invoke(env={}, shell_path=str(self.tools))
        self.assertEqual(result, 0, output)
        self.assertEqual(run.call_count, 4)
        self.assertEqual(run.call_args_list[0].args[0], ['sh', '-c', 'printf "%s" "$PATH"'])
        self.assertEqual(run.call_args_list[1].kwargs['env'], {'PATH': f'{self.tools}:{self.tools}'})

    def test_unset_path_probe_failures_return_without_further_processes(self):
        for failure in (FileNotFoundError('sh'), subprocess.TimeoutExpired(['sh'], 5)):
            with self.subTest(failure=type(failure).__name__):
                result, output, run = self.invoke(env={}, shell_path=failure)
                self.assertEqual(result, 1)
                self.assertIn('MISSING: shell search path:', output)
                self.assertNotIn('Traceback', output)
                self.assertEqual(run.call_count, 1)

    def test_empty_and_relative_path_find_tools_in_launch_directory(self):
        for path, cwd in (('', self.tools), (self.tools.name, self.root)):
            with self.subTest(path=path), contextlib.chdir(cwd):
                result, output, run = self.invoke(env={'PATH': path})
                self.assertEqual(result, 0, output)
                self.assertEqual(run.call_count, 3)

    def test_archives_use_explicit_paths_and_report_each_missing_source(self):
        selected = self.root / 'selected qemu archive'
        selected.write_bytes(b'presence only')
        environment = {'PATH': str(self.tools), 'HARMATTAN_QEMU_TARBALL': str(selected)}
        result, output, _ = self.invoke(env=environment)
        self.assertEqual(result, 0, output)
        self.assertIn(f'OK: source archive qemu-source: {selected}', output)
        selected.unlink()
        (self.root / 'sources/dgles.tar.gz').unlink()
        result, output, _ = self.invoke(env=environment)
        self.assertEqual(result, 1)
        self.assertIn(f'MISSING: source archive qemu-source: {selected}', output)
        self.assertIn(f'MISSING: source archive dgles-source: {self.root / "sources/dgles.tar.gz"}', output)

    def test_archive_stat_errors_are_reported_without_stopping_other_checks(self):
        original_is_file = Path.is_file

        def is_file(path):
            if path == self.root / 'sources/qemu.tar.xz':
                raise PermissionError('synthetic archive stat denial')
            return original_is_file(path)

        with patch.object(Path, 'is_file', is_file):
            result, output, run = self.invoke()
        self.assertEqual(result, 1)
        self.assertIn('MISSING: source archive qemu-source:', output)
        self.assertIn('PermissionError: synthetic archive stat denial', output)
        self.assertIn('OK: source archive dgles-source:', output)
        self.assertNotIn('Traceback', output)
        self.assertEqual(run.call_count, 3)

    def test_source_only_checks_do_not_read_guest_or_archive_contents_or_write(self):
        original_is_file, original_read_text = Path.is_file, Path.read_text
        checked, read = [], []

        def is_file(path):
            checked.append(path)
            self.assertIn(path, [self.root / item['path'] for item in self.manifest['inputs'][:2]])
            return original_is_file(path)

        def read_text(path, *args, **kwargs):
            read.append(path)
            self.assertEqual(path, self.root / 'docs/inputs.json')
            return original_read_text(path, *args, **kwargs)

        environment = {'PATH': str(self.tools), 'HARMATTAN_KERNEL': '/must/not/read/kernel',
                       'HARMATTAN_GUEST_IMAGE': '/must/not/read/disk',
                       'HARMATTAN_PUBLIC_ROOTFS': '/must/not/read/rootfs',
                       'HARMATTAN_USER_PROFILE': '/must/not/create/profile',
                       'HARMATTAN_ARMEL_CLANG': 'missing', 'HARMATTAN_DEBUGFS': 'missing'}
        with patch.object(Path, 'is_file', is_file), patch.object(Path, 'read_text', read_text), \
                patch.object(Path, 'read_bytes', side_effect=AssertionError('unexpected file read')), \
                patch.object(Path, 'write_text', side_effect=AssertionError('unexpected write')), \
                patch.object(Path, 'write_bytes', side_effect=AssertionError('unexpected write')), \
                patch.object(Path, 'mkdir', side_effect=AssertionError('unexpected mkdir')):
            result, output, run = self.invoke(env=environment)
        self.assertEqual(result, 0, output)
        self.assertEqual(len(checked), 2)
        self.assertEqual(read, [self.root / 'docs/inputs.json'])
        self.assertEqual(run.call_count, 3)
        self.assertNotIn('guest-kernel', output)
        self.assertNotIn('optional-artwork', output)
        self.assertFalse((self.root / 'extracted').exists())

    def test_unsupported_hosts_and_old_running_python_fail(self):
        for kwargs, report in (({'system': 'Darwin', 'machine': 'arm64'}, 'Linux build host'),
                               ({'machine': 'aarch64'}, 'Linux build host'),
                               ({'version': (3, 11)}, 'running Python')):
            with self.subTest(kwargs=kwargs):
                result, output, _ = self.invoke(**kwargs)
                self.assertEqual(result, 1)
                self.assertIn(f'MISSING: {report}:', output)

    def test_linux_build_and_guest_flags_are_rejected_before_probes(self):
        errors = io.StringIO()
        with patch.object(CHECK, 'linux_build_check') as linux, \
                patch.object(CHECK.subprocess, 'run') as run, \
                contextlib.redirect_stderr(errors), self.assertRaises(SystemExit) as raised:
            CHECK.main(['--linux-build', '--guest'])
        self.assertEqual(raised.exception.code, 2)
        self.assertIn('--linux-build cannot be combined with --guest', errors.getvalue())
        linux.assert_not_called()
        run.assert_not_called()

    def legacy_output(self, *, guest=False):
        text = ('OK: native host: Darwin arm64 (full runtime requires Apple Silicon macOS)\n'
                'OK: Python: 3.12\n'
                f'OK: clang: {self.tools / "clang"}\n'
                f'OK: ninja: {self.tools / "ninja"}\n'
                f'OK: pkg-config: {self.tools / "pkg-config"}\n'
                'OK: glib-2.0: pkg-config development dependency\n'
                'OK: pixman-1: pkg-config development dependency\n'
                'OK: slirp: pkg-config development dependency\n'
                f'OK: qemu-source: {self.root / "sources/qemu.tar.xz"}\n'
                f'OK: dgles-source: {self.root / "sources/dgles.tar.gz"}\n')
        if guest:
            text += (f'MISSING: guest-kernel: {self.root / "guest/kernel"}\n'
                     'OPTIONAL: optional-artwork: absent\n'
                     f'OK: HARMATTAN_ARMEL_CLANG: {self.tools / "clang"}\n'
                     f'OK: HARMATTAN_DEBUGFS: {self.tools / "debugfs"}\n')
        return text + ('Checks file presence/tool discovery only; build scripts verify pinned hashes. '
                       'APFS cloning, graphics execution, ARM/lld capability, and guest contents '
                       'require runtime validation.\n')

    def test_legacy_no_flag_transcript_and_success_are_unchanged(self):
        result, output, run = self.invoke(args=(), system='Darwin', machine='arm64')
        self.assertEqual(result, 0)
        self.assertEqual(output, self.legacy_output())
        self.assertEqual([call.args[0] for call in run.call_args_list], [
            ['pkg-config', '--exists', package] for package in ('glib-2.0', 'pixman-1', 'slirp')])
        self.assertTrue(all(call.kwargs == {'check': False} for call in run.call_args_list))

    def test_legacy_guest_transcript_and_missing_guest_exit_are_unchanged(self):
        result, output, _ = self.invoke(args=('--guest',), system='Darwin', machine='arm64')
        self.assertEqual(result, 1)
        self.assertEqual(output, self.legacy_output(guest=True))

    def test_legacy_empty_overrides_keep_their_original_failure_behavior(self):
        result, output, _ = self.invoke(args=(), system='Darwin', machine='arm64', env={
            'PATH': str(self.tools), 'HARMATTAN_CC': '', 'HARMATTAN_NINJA': '',
            'HARMATTAN_QEMU_TARBALL': '', 'HARMATTAN_GLES_TARBALL': ''})
        self.assertEqual(result, 1)
        for name in ('clang', 'ninja', 'qemu-source', 'dgles-source'):
            self.assertIn(f'MISSING: {name}: \n', output)


if __name__ == '__main__':
    unittest.main()
