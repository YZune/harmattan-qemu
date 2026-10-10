"""Isolated Godot frontend checks; no guest media, desktop, or QEMU required.

Set HARMATTAN_GODOT to an installed Godot 4.6+ executable, or put godot4/godot
on PATH. Auto-discovery skips this suite when a supported Godot is absent.
An explicit HARMATTAN_GODOT that cannot run fails instead of silently skipping.
All generated files, including Godot caches, stay in a temporary directory.
"""
# Copyright (C) 2026 YZune and contributors.
# SPDX-License-Identifier: GPL-2.0-or-later
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
FRONTEND = ROOT / 'ports/linux-native-ui'
FIXTURES = Path(__file__).parent / 'fixtures/linux-native-ui'


@unittest.skipUnless(os.name == 'posix', 'frontend requires Unix session permissions')
class LinuxFrontendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        configured = os.environ.get('HARMATTAN_GODOT')
        candidates = [configured] if configured else ['godot4', 'godot']
        for candidate in candidates:
            executable = shutil.which(candidate)
            if not executable:
                continue
            with tempfile.TemporaryDirectory(prefix='harmattan-godot-version-') as tmp:
                env = os.environ | {'XDG_CACHE_HOME': tmp}
                result = subprocess.run([executable, '--version'], env=env,
                                        capture_output=True, text=True, timeout=15)
            match = re.search(r'(?m)^4\.(\d+)\.', result.stdout)
            if result.returncode == 0 and match and int(match[1]) >= 6:
                cls.godot = str(Path(executable).resolve())
                return
        if configured:
            raise RuntimeError('HARMATTAN_GODOT must name a runnable Godot 4.6+ executable')
        raise unittest.SkipTest('Godot 4.6+ not installed; set HARMATTAN_GODOT to run frontend checks')

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='harmattan-frontend-')
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.project = self.base / 'project'
        self.project.mkdir()
        for filename in ('project.godot', 'main.tscn', 'main.gd', 'main.gd.uid'):
            shutil.copyfile(FRONTEND / filename, self.project / filename)
        for fixture in FIXTURES.glob('*.gd'):
            shutil.copyfile(fixture, self.project / fixture.name)
        self.session = self.base / 'private session'
        self.session.mkdir(mode=0o700)
        (self.session / 'events').mkdir(mode=0o700)
        self.env = os.environ | {
            'XDG_CACHE_HOME': str(self.base / 'cache'),
            'XDG_CONFIG_HOME': str(self.base / 'config'),
            'XDG_DATA_HOME': str(self.base / 'data'),
            'GODOT_SILENCE_ROOT_WARNING': '1',
        }

    def run_godot(self, arguments, script=None):
        command = [self.godot, '--headless', '--path', str(self.project)]
        if script:
            command += ['--script', 'res://' + script]
        else:
            command += ['--quit-after', '2']
        return subprocess.run(command + ['--'] + arguments, cwd=self.project,
                              env=self.env, capture_output=True, text=True, timeout=30)

    def assert_probe(self, metrics):
        arguments = ['--session', str(self.session)] + (['--metrics'] if metrics else [])
        result = self.run_godot(arguments, 'probe.gd')
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn('SCRIPT ERROR', output)
        self.assertNotIn('FAILED:', output)
        reports = [json.loads(line) for line in result.stdout.splitlines()
                   if line.startswith('{')]
        self.assertEqual(len(reports), 1, output)
        self.assertEqual(reports[0]['result'], 'passed')
        self.assertGreaterEqual(reports[0]['checks'], 227)
        telemetry = list(self.session.glob('telemetry.*.jsonl'))
        self.assertEqual(bool(telemetry), metrics)
        for path in telemetry:
            records = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertTrue(records)
            for record in records:
                self.assertNotIn('key', record)
                self.assertNotIn('text', record)
        # Events are the actual input protocol; they retain typed keys even
        # when optional metrics are disabled. Only the private controller reads them.
        keys = [json.loads(path.read_text()) for path in (self.session / 'events').glob('*.json')]
        self.assertTrue(any(event.get('key') == 'x' for event in keys))

    def test_ordering_rate_lifecycle_and_default_metrics_off(self):
        self.assert_probe(metrics=False)

    def test_explicit_metrics_preserve_ordering_and_omit_text(self):
        self.assert_probe(metrics=True)

    def test_supervised_exit_requires_fresh_success_and_preserves_manual_default(self):
        result = self.run_godot(['--session', str(self.session), '--exit-with-controller'], 'probe_controller_exit.gd')
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn('SCRIPT ERROR', output)
        self.assertNotIn('FAILED:', output)
        reports = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
        self.assertEqual(reports, [{'checks': 38, 'result': 'passed'}])

    def test_storage_notice_is_optional_private_and_does_not_change_readiness(self):
        result = self.run_godot(['--session', str(self.session)], 'probe_storage_notice.gd')
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0, output)
        self.assertNotIn('SCRIPT ERROR', output)
        self.assertNotIn('FAILED:', output)
        reports = [json.loads(line) for line in result.stdout.splitlines() if line.startswith('{')]
        self.assertEqual(reports, [{'checks': 58, 'result': 'passed'}])

    def test_existing_private_session_starts_without_metrics(self):
        result = self.run_godot(['--session', str(self.session)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('SCRIPT ERROR', result.stderr)
        self.assertEqual(list(self.session.iterdir()), [self.session / 'events'])

    def test_bad_arguments_fail_closed_without_creating_session(self):
        missing = self.base / 'must not be created'
        cases = [([], 'Required:'), (['--metrics'], 'Required:'),
                 (['--session'], 'Pass --session once'),
                 (['--session', 'relative'], 'Required:'),
                 (['--session', 'res://session'], 'Required:'),
                 (['--session', str(missing)], 'must already be real directories'),
                 (['--session', str(self.session), '--session', str(self.session)], 'Pass --session once'),
                 (['--session', '', '--session', str(self.session)], 'Pass --session once'),
                 (['--session', str(self.session), '--metrics', '--metrics'], 'at most once'),
                 (['--session', str(self.session), '--exit-with-controller', '--exit-with-controller'], 'at most once'),
                 (['--session', str(self.session), '--unknown'], 'Unknown frontend argument'),
                 (['--session', str(self.session) + '/../private session'], 'normalized absolute')]
        for arguments, message in cases:
            with self.subTest(arguments=arguments):
                result = self.run_godot(arguments)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn(message, result.stderr)
                self.assertNotIn('SCRIPT ERROR', result.stderr)
        self.assertFalse(missing.exists())
        self.assertEqual(list(self.session.iterdir()), [self.session / 'events'])
        self.assertEqual(list((self.session / 'events').iterdir()), [])

    def test_configuration_error_is_visible_and_disables_io(self):
        result = self.run_godot(['--metrics'], 'probe_invalid.gd')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('SCRIPT ERROR', result.stderr)
        self.assertIn('configuration fail-closed checks passed', result.stdout)

    def test_missing_events_and_unsafe_directory_modes_fail_closed(self):
        empty = self.base / 'empty session'
        empty.mkdir(mode=0o700)
        result = self.run_godot(['--session', str(empty)])
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertFalse((empty / 'events').exists())
        for directory in (self.session, self.session / 'events'):
            for mode in (0o755, 0o770, 0o1700):
                with self.subTest(directory=directory.name, mode=oct(mode)):
                    directory.chmod(mode)
                    try:
                        result = self.run_godot(['--session', str(self.session)])
                    finally:
                        directory.chmod(0o700)
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertIn('mode-0700', result.stderr)

    def test_symlink_session_and_events_fail_closed(self):
        linked = self.base / 'linked session'
        linked.symlink_to(self.session, target_is_directory=True)
        result = self.run_godot(['--session', str(linked)])
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        events = self.session / 'events'
        events.rename(self.session / 'original events')
        events.symlink_to(self.session / 'original events', target_is_directory=True)
        result = self.run_godot(['--session', str(self.session)])
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertEqual(list((self.session / 'original events').iterdir()), [])


if __name__ == '__main__':
    unittest.main()
