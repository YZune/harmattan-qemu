"""Synthetic subprocess lifecycle checks, not a guest boot or native UI pass."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import test_linux_ui as linux_ui

SCRIPTS = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('native_supervisor', SCRIPTS / 'native-supervisor.py')
SUPERVISOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SUPERVISOR)
LAUNCHER = linux_ui.LAUNCHER

# Each process is real; only the bridge/guest evidence is synthetic. The fixture
# never invokes QEMU, Godot, or any guest validator.
PROGRAM = r'''
import json, os, pathlib, signal, subprocess, sys, time
role, location, scenario = sys.argv[1:]
session = pathlib.Path(location)
parent = session.parent
(parent / (role + '-pid')).write_text(str(os.getpid()))
def wait_for(predicate):
    deadline = time.monotonic() + 8
    while not predicate():
        if time.monotonic() >= deadline:
            raise RuntimeError('synthetic fixture wait expired')
        time.sleep(.01)
def status(state='starting', **extra):
    data = dict(v=1, controller_id='a' * 32, width=480, height=864,
                ready=False, state=state, updated_ms=round(time.time() * 1000))
    data.update(extra)
    temporary = session / '.status'
    temporary.write_text(json.dumps(data))
    temporary.chmod(0o600)
    temporary.replace(session / 'status.json')
def descendant():
    child = "import os,pathlib,signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); pathlib.Path(" + repr(str(parent / 'descendant-pid')) + ").write_text(str(os.getpid())); time.sleep(20)"
    subprocess.Popen([sys.executable, '-c', child])
    wait_for(lambda: (parent / 'descendant-pid').exists())
if role == 'controller':
    if scenario == 'no_session':
        time.sleep(20)
    elif scenario == 'failed_before_session':
        sys.exit(9)
    session.mkdir(mode=0o700)
    (session / 'events').mkdir(mode=0o700)
    if scenario == 'invalid_json':
        (session / 'status.json').write_text('{broken')
        (session / 'status.json').chmod(0o600)
    elif scenario == 'stale_status':
        status(updated_ms=round(time.time() * 1000) - 10000)
    elif scenario == 'wrong_identity':
        status(controller_id='not-a-controller')
    elif scenario == 'unsafe_directory':
        session.chmod(0o755)
        status()
    else:
        status()
    if scenario in ('invalid_json', 'stale_status', 'wrong_identity', 'unsafe_directory'):
        time.sleep(20)
    wait_for(lambda: (parent / 'frontend-started').exists())
    if scenario in ('controller_crash', 'hang'):
        descendant()
    if scenario == 'controller_crash':
        sys.exit(7)
    if scenario in ('early_zero', 'frontend_failure', 'hang', 'interrupt', 'frontend_spawn_failure'):
        time.sleep(20)
    if scenario == 'cancelled':
        status('cancelled', passed=False, qemu_exit=0)
        sys.exit(1)
    if scenario == 'no_acceptance':
        sys.exit(0)
    if scenario == 'wrong_terminal_identity':
        status('exited', controller_id='b' * 32, passed=True, qemu_exit=0)
    else:
        status('exited', passed=True, qemu_exit=0)
    if scenario == 'frontend_first':
        time.sleep(.15)
    if scenario == 'controller_hangs_after_terminal':
        time.sleep(20)
    sys.exit(0)
else:
    assert session.is_dir() and (session / 'events').is_dir()
    assert json.loads((session / 'status.json').read_text())['state'] == 'starting'
    (parent / 'frontend-started').touch()
    if scenario == 'early_zero':
        sys.exit(0)
    if scenario == 'frontend_failure':
        sys.exit(23)
    if scenario in ('controller_crash', 'hang', 'interrupt', 'cancelled', 'no_acceptance', 'frontend_hangs'):
        time.sleep(20)
    wait_for(lambda: json.loads((session / 'status.json').read_text()).get('state') == 'exited')
    if scenario == 'controller_first':
        time.sleep(.15)
    sys.exit(0)
'''


@unittest.skipUnless(os.name == 'posix', 'POSIX process groups and file ownership')
class NativeSupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.program = self.root / 'fixture.py'
        self.program.write_text(PROGRAM)

    def commands(self, scenario, name='run'):
        out = self.root / name
        out.mkdir(mode=0o700)
        session = out / 'session'
        controller = [sys.executable, '-u', str(self.program), 'controller', str(session), scenario]
        frontend = [sys.executable, '-u', str(self.program), 'frontend', str(session), scenario]
        return out, session, controller, frontend

    def run_fixture(self, scenario, **options):
        out, session, controller, frontend = self.commands(scenario)
        result = SUPERVISOR.run(controller, os.environ.copy(), frontend, os.environ.copy(),
                                out, session, options.pop('timeout', 3),
                                session_wait=options.pop('session_wait', 1),
                                frontend_grace=.4, stop_grace=.2, **options)
        self.assert_stopped(out)
        return result, out

    def assert_stopped(self, out):
        for name in ('controller-pid', 'frontend-pid', 'descendant-pid'):
            path = out / name
            if not path.exists():
                continue
            pid = int(path.read_text())
            for attempt in range(100):
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
                # A dead orphan can briefly remain an init-owned zombie on
                # Linux; it is not a running leaked controller or QEMU.
                proc = Path(f'/proc/{pid}/stat')
                if sys.platform == 'linux' and proc.exists():
                    try:
                        if proc.read_text().split(') ', 1)[1].startswith('Z '):
                            break
                    except FileNotFoundError:
                        break
                time.sleep(.01)
            else:
                os.kill(pid, signal.SIGKILL)
                self.fail(f'owned synthetic {name} still running')

    def test_clean_exit_in_both_orders(self):
        for scenario in ('frontend_first', 'controller_first'):
            with self.subTest(scenario=scenario):
                out, session, controller, frontend = self.commands(scenario, scenario)
                result = SUPERVISOR.run(controller, os.environ.copy(), frontend, os.environ.copy(),
                                        out, session, 3, frontend_grace=.5, stop_grace=.2)
                self.assert_stopped(out)
                self.assertTrue(result['completed'], result)
                self.assertEqual((result['controller_exit'], result['frontend_exit']), (0, 0))
                self.assertEqual(result['frontend_stop'], 'natural')

    def test_early_frontend_exit_never_establishes_guest_acceptance(self):
        for scenario, code in (('early_zero', 0), ('frontend_failure', 23)):
            with self.subTest(scenario=scenario):
                out, session, controller, frontend = self.commands(scenario, scenario)
                result = SUPERVISOR.run(controller, os.environ.copy(), frontend, os.environ.copy(),
                                        out, session, 3, stop_grace=.2)
                self.assert_stopped(out)
                self.assertFalse(result['completed'])
                self.assertEqual(result['frontend_exit'], code)
                self.assertIn('frontend', result['failure'])

    def test_controller_crash_closes_window_and_term_ignoring_descendant(self):
        result, unused = self.run_fixture('controller_crash')
        self.assertFalse(result['completed'])
        self.assertEqual(result['controller_exit'], 7)
        self.assertEqual(result['frontend_stop'], 'supervisor_cleanup')

    def test_controller_runtime_timeout_reaps_both_groups(self):
        result, unused = self.run_fixture('hang', timeout=.7)
        self.assertFalse(result['completed'])
        self.assertIn('bounded runtime', result['failure'])

    def test_frontend_start_failure_stops_controller(self):
        out, session, controller, unused = self.commands('frontend_spawn_failure')
        result = SUPERVISOR.run(controller, os.environ.copy(), [str(out / 'missing-godot')],
                                os.environ.copy(), out, session, 3, stop_grace=.2)
        self.assert_stopped(out)
        self.assertFalse(result['completed'])
        self.assertFalse(result['frontend_started'])
        self.assertIn('FileNotFoundError', result['failure'])

    def test_absent_session_has_separate_bounded_startup_failure(self):
        result, out = self.run_fixture('no_session', session_wait=.3)
        self.assertIn('fresh native session', result['failure'])
        self.assertFalse((out / 'frontend-started').exists())

    def test_controller_failure_before_session_never_opens_frontend(self):
        result, out = self.run_fixture('failed_before_session')
        self.assertEqual(result['controller_exit'], 9)
        self.assertFalse((out / 'frontend-started').exists())

    def test_untrusted_initial_status_never_opens_frontend(self):
        for scenario in ('invalid_json', 'stale_status', 'wrong_identity', 'unsafe_directory'):
            with self.subTest(scenario=scenario):
                out, session, controller, frontend = self.commands(scenario, scenario)
                result = SUPERVISOR.run(controller, os.environ.copy(), frontend, os.environ.copy(),
                                        out, session, 3, stop_grace=.2)
                self.assert_stopped(out)
                self.assertFalse(result['completed'])
                self.assertFalse(result['frontend_started'])

    def test_terminal_failure_or_missing_acceptance_cannot_pass(self):
        for scenario in ('cancelled', 'no_acceptance', 'wrong_terminal_identity'):
            with self.subTest(scenario=scenario):
                out, session, controller, frontend = self.commands(scenario, scenario)
                result = SUPERVISOR.run(controller, os.environ.copy(), frontend, os.environ.copy(),
                                        out, session, 3, stop_grace=.2)
                self.assert_stopped(out)
                self.assertFalse(result['completed'])
                self.assertIn('failure', result)

    def test_terminal_status_does_not_allow_either_process_to_hang(self):
        for scenario in ('frontend_hangs', 'controller_hangs_after_terminal'):
            with self.subTest(scenario=scenario):
                out, session, controller, frontend = self.commands(scenario, scenario)
                result = SUPERVISOR.run(controller, os.environ.copy(), frontend, os.environ.copy(),
                                        out, session, 3, frontend_grace=.2, stop_grace=.2)
                self.assert_stopped(out)
                self.assertFalse(result['completed'])
                self.assertIn('TimeoutError', result['failure'])

    def test_existing_session_is_not_reused_or_modified(self):
        out, session, controller, frontend = self.commands('controller_first')
        session.mkdir()
        sentinel = session / 'keep'
        sentinel.write_text('previous run evidence')
        with self.assertRaisesRegex(ValueError, 'already exists'):
            SUPERVISOR.run(controller, {}, frontend, {}, out, session, 1)
        self.assertEqual(sentinel.read_text(), 'previous run evidence')
        self.assertFalse((out / 'controller-pid').exists())

    def test_repeated_launches_use_distinct_owned_sessions(self):
        identities = []
        for number in range(2):
            out, session, controller, frontend = self.commands('controller_first', f'run-{number}')
            result = SUPERVISOR.run(controller, os.environ.copy(), frontend, os.environ.copy(),
                                    out, session, 3, frontend_grace=.5, stop_grace=.2)
            self.assertTrue(result['completed'], result)
            self.assert_stopped(out)
            identities.append(session.stat().st_ino)
        self.assertNotEqual(*identities)

    def test_concurrent_launches_do_not_share_sessions_or_cleanup(self):
        processes = []
        try:
            for number in range(2):
                out, session, controller, frontend = self.commands('controller_first', f'parallel-{number}')
                driver = ("import importlib.util,json,os,pathlib; "
                          f"s=importlib.util.spec_from_file_location('supervisor', {str(SCRIPTS / 'native-supervisor.py')!r}); "
                          "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
                          f"r=m.run({controller!r},os.environ.copy(),{frontend!r},os.environ.copy(),{str(out)!r},{str(session)!r},3,frontend_grace=.5,stop_grace=.2); "
                          f"pathlib.Path({str(out / 'result.json')!r}).write_text(json.dumps(r))")
                processes.append((subprocess.Popen([sys.executable, '-c', driver]), out))
            for process, out in processes:
                self.assertEqual(process.wait(timeout=4), 0)
                result = json.loads((out / 'result.json').read_text())
                self.assertTrue(result['completed'], result)
                self.assert_stopped(out)
        finally:
            for process, unused in processes:
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=3)

    def test_signal_handlers_are_restored_after_success(self):
        before = {number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGTERM)}
        result, unused = self.run_fixture('controller_first')
        self.assertTrue(result['completed'], result)
        self.assertEqual({number: signal.getsignal(number) for number in before}, before)

    def test_status_symlinks_and_special_files_are_rejected(self):
        session = self.root / 'session'
        session.mkdir(mode=0o700)
        (session / 'events').mkdir(mode=0o700)
        target = self.root / 'other-status'
        target.write_text('{}')
        target.chmod(0o600)
        status = session / 'status.json'
        status.symlink_to(target)
        with self.assertRaises(OSError):
            SUPERVISOR.SessionStatus(session, 0).read()
        status.unlink()
        os.mkfifo(status, 0o600)
        with self.assertRaisesRegex(ValueError, 'regular file'):
            SUPERVISOR.SessionStatus(session, 0).read()

    def test_interrupts_stop_both_groups_and_preserve_unrelated_process(self):
        unrelated = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(20)'], start_new_session=True)
        self.addCleanup(lambda: SUPERVISOR.stop_group(unrelated, .2))
        for number in (signal.SIGINT, signal.SIGTERM):
            with self.subTest(signal=number):
                out, session, controller, frontend = self.commands('interrupt', str(number))
                driver = ("import importlib.util,json,os,pathlib; "
                          f"s=importlib.util.spec_from_file_location('supervisor', {str(SCRIPTS / 'native-supervisor.py')!r}); "
                          "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
                          f"r=m.run({controller!r},os.environ.copy(),{frontend!r},os.environ.copy(),{str(out)!r},{str(session)!r},10,stop_grace=.2); "
                          f"pathlib.Path({str(out / 'result.json')!r}).write_text(json.dumps(r))")
                process = subprocess.Popen([sys.executable, '-c', driver])
                try:
                    deadline = time.monotonic() + 3
                    while not (out / 'frontend-started').exists():
                        self.assertIsNone(process.poll())
                        self.assertLess(time.monotonic(), deadline)
                        time.sleep(.01)
                    process.send_signal(number)
                    self.assertEqual(process.wait(timeout=3), 0)
                    result = json.loads((out / 'result.json').read_text())
                    self.assertFalse(result['completed'])
                    self.assertIn(signal.Signals(number).name, result['failure'])
                    self.assert_stopped(out)
                    self.assertIsNone(unrelated.poll())
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=3)


class NativeLauncherCommandTests(unittest.TestCase):
    def test_supervised_command_defaults_fresh_session_and_isolates_environments(self):
        for metrics in (False, True):
            with self.subTest(metrics=metrics), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                args, prepared = linux_ui.LinuxLauncherTests().fixture(root)
                args += ['--mode', 'live', '--frontend', sys.executable]
                if metrics:
                    args += ['--metrics']
                observed = []
                def supervise(command, env, frontend, frontend_env, output, session, timeout):
                    observed.append((command, env, frontend, frontend_env, output, session))
                    (output / 'ui').mkdir()
                    (output / 'ui/startup-result.json').write_text('{"passed": true}')
                    return {'completed': True, 'controller_exit': 0, 'frontend_exit': 0}
                kernel_sha = hashlib.sha256((prepared / 'zImage-2.6.32.26-qemu').read_bytes()).hexdigest()
                with patch.dict(os.environ, {'DISPLAY': ':synthetic', 'LD_LIBRARY_PATH': '/original-host'}, clear=True), \
                     patch.object(LAUNCHER.sys, 'platform', 'linux'), patch.object(LAUNCHER, 'KERNEL_SHA256', kernel_sha), \
                     patch.object(LAUNCHER.linux_offscreen, 'require_pillow'), patch.object(LAUNCHER.subprocess, 'run'), \
                     patch.object(LAUNCHER.native_supervisor, 'run', side_effect=supervise), \
                     patch.object(LAUNCHER, 'run_controller') as manual, contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(LAUNCHER.main(args), 0)
                    manual.assert_not_called()
                command, env, frontend, frontend_env, output, session = observed[0]
                self.assertEqual(session, output / 'session')
                self.assertEqual(command[command.index('--linux-live-session') + 1], str(session))
                self.assertEqual(frontend[frontend.index('--session') + 1], str(session))
                self.assertIn('--exit-with-controller', frontend)
                self.assertEqual(frontend[frontend.index('--audio-driver') + 1], 'Dummy')
                self.assertEqual('--metrics' in frontend, metrics)
                self.assertEqual('--linux-live-metrics' in command, metrics)
                self.assertEqual(frontend_env['LD_LIBRARY_PATH'], '/original-host')
                self.assertNotIn('EGL_PLATFORM', frontend_env)
                self.assertEqual(env['EGL_PLATFORM'], 'surfaceless')
                self.assertEqual(command[command.index('-nic') + 1], 'none')
                self.assertIn('-snapshot', command)
                self.assertNotIn('--headless', frontend)

    @unittest.skipUnless(os.name == 'posix', 'POSIX process groups')
    def test_clean_subprocess_lifecycle_still_requires_original_controller_result(self):
        for acceptance in (None, False, True):
            with self.subTest(acceptance=acceptance), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                args, prepared = linux_ui.LinuxLauncherTests().fixture(root)
                program = root / 'fixture.py'
                program.write_text(PROGRAM)
                args += ['--mode', 'live', '--frontend', sys.executable]
                actual_supervise = SUPERVISOR.run
                def supervise(unused_controller, env, unused_frontend, frontend_env, output, session, timeout):
                    controller = [sys.executable, '-u', str(program), 'controller', str(session), 'controller_first']
                    frontend = [sys.executable, '-u', str(program), 'frontend', str(session), 'controller_first']
                    result = actual_supervise(controller, env, frontend, frontend_env, output, session,
                                              3, frontend_grace=.5, stop_grace=.2)
                    if acceptance is not None:
                        (output / 'ui').mkdir()
                        (output / 'ui/startup-result.json').write_text(json.dumps({'passed': acceptance}))
                    return result
                kernel_sha = hashlib.sha256((prepared / 'zImage-2.6.32.26-qemu').read_bytes()).hexdigest()
                errors = io.StringIO()
                with patch.dict(os.environ, {'DISPLAY': ':synthetic'}, clear=True), \
                     patch.object(LAUNCHER.sys, 'platform', 'linux'), patch.object(LAUNCHER, 'KERNEL_SHA256', kernel_sha), \
                     patch.object(LAUNCHER.linux_offscreen, 'require_pillow'), patch.object(LAUNCHER.subprocess, 'run'), \
                     patch.object(LAUNCHER.native_supervisor, 'run', side_effect=supervise), \
                     contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(errors):
                    self.assertEqual(LAUNCHER.main(args), 0 if acceptance else 1)
                record = json.loads((root / 'run/launch-result.json').read_text())
                self.assertTrue(record['native_lifecycle']['completed'], record)
                self.assertEqual(record['passed'], acceptance is True)
                if not acceptance:
                    self.assertIn('Linux native launch failed', errors.getvalue())
                    self.assertIn(str(root / 'run'), errors.getvalue())

    def test_invalid_frontend_configuration_fails_before_guest_execution(self):
        cases = [(['--frontend', sys.executable], {'DISPLAY': ':synthetic'}),
                 (['--mode', 'live', '--frontend', '/missing-godot'], {'DISPLAY': ':synthetic'}),
                 (['--mode', 'live', '--frontend', sys.executable], {}),
                 (['--mode', 'live', '--frontend', sys.executable, '--prepare-only'], {'DISPLAY': ':synthetic'})]
        for extra, env in cases:
            with self.subTest(extra=extra, env=env), tempfile.TemporaryDirectory() as tmp:
                args, unused = linux_ui.LinuxLauncherTests().fixture(Path(tmp))
                with patch.dict(os.environ, env, clear=True), patch.object(LAUNCHER.sys, 'platform', 'linux'), \
                     patch.object(LAUNCHER.subprocess, 'run') as execute, contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as error:
                        LAUNCHER.main(args + extra)
                    self.assertEqual(error.exception.code, 2)
                    execute.assert_not_called()


if __name__ == '__main__':
    unittest.main()
