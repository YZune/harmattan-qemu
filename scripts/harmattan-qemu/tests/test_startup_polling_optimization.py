"""Host-only service polling checks; no guest programs or devices are used."""
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import unittest

from test_arm64_keyboard import KEYBOARD, service as ime_report
from test_arm64_systemui import UI, report as systemui_report


SCRIPTS = Path(__file__).resolve().parents[1]


class ServicePollingTests(unittest.TestCase):
    def run_report(self, service, failure='', bad_hash=False, owner='123', state='S', readiness_first=None):
        filename, function = (('diagnose-shell-guest.sh', 'report_systemui') if service == 'systemui'
                              else ('input-method-guest.sh', 'report_input_method'))
        source = (SCRIPTS / filename).read_text()
        report = re.search(r'^' + function + r'\(\) \{\n.*?^\}', source, re.M | re.S).group()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = report.replace('/tmp/n00-systemui-process.log', str(root / 'systemui.log'))
            report = report.replace('/tmp/n00-ime-process.log', str(root / 'ime.log'))
            cmdline = root / 'cmdline'
            cmdline.write_bytes(b'meego-im-uiserver\0-use-self-composition\0-software\0-local-theme\0-graphicssystem\0raster\0')
            report = report.replace('"/proc/$ime_pid/cmdline"', shlex.quote(str(cmdline)))
            trace = root / 'trace'
            prelude = r'''set -eu
user_env='DISPLAY=:9'
pidof() { [ "$FAIL_STEP" != process ] || return 1; printf '123\n'; }
sed() {
    printf 'Name:\t%s\nState:\t%s (test)\nTgid:\t123\nPid:\t123\nPPid:\t1\nTracerPid:\t0\nUid:\t29999\t29999\t29999\t29999\n' "$PROCESS_NAME" "$STATE"
}
grep() {
    case "$*" in
        *'/proc/123/maps'*)
            printf 'mapping\n' >> "$TRACE"
            [ "$FAIL_STEP" != mapping ] ;;
        *) command grep "$@" ;;
    esac
}
sleep() { printf 'sleep %s\n' "$*" >> "$TRACE"; }
readlink() { printf 'identity\n' >> "$TRACE"; printf '/usr/bin/%s\n' "$EXECUTABLE"; }
md5sum() {
    printf 'hashes\n' >> "$TRACE"
    for path in "$@"; do
        case "$path" in
            /usr/bin/sysuid) digest=6e6ca0153aea0bf3b4556c08d68f934f ;;
            /usr/bin/meego-im-uiserver) digest=bf6a04592241f1764a669324a330b0f1 ;;
            /proc/123/exe) digest="$EXECUTABLE_MD5" ;;
            /usr/lib/meego-im-plugins/libmeego-keyboard.so) digest=3436d74757597eb83207ab86158788c4 ;;
            /usr/lib/qt4/plugins/inputmethods/libminputcontext.so) digest=6877d40e5cdba786a62acaaa4ceb20c3 ;;
            *) return 2 ;;
        esac
        if [ "$BAD_HASH" = 1 ]; then digest=00000000000000000000000000000000; fi
        printf '%s  %s\n' "$digest" "$path"
    done
}
su() {
    case "$*" in
        *GetConnectionUnixProcessID*)
            printf 'owner\n' >> "$TRACE"
            [ "$FAIL_STEP" != owner ] || return 1
            printf 'method return\n   uint32 %s\n' "$OWNER" ;;
        *sharedPixmapHandle*)
            printf 'pixmap\n' >> "$TRACE"
            [ "$FAIL_STEP" != pixmap ] || return 1
            printf 'method return\n   uint32 6291478\n' ;;
        *org.freedesktop.DBus.Properties.Get*)
            printf 'address\n' >> "$TRACE"
            [ "$FAIL_STEP" != address ] || return 1
            printf '   variant string "unix:abstract=/tmp/maliit-server/dbus-Abc123,guid=0123456789abcdef0123456789abcdef"\n' ;;
        *) return 2 ;;
    esac
}
'''
            env = os.environ | {'TRACE': str(trace), 'FAIL_STEP': failure,
                'BAD_HASH': str(int(bad_hash)), 'OWNER': owner, 'STATE': state,
                'PROCESS_NAME': 'sysuid' if service == 'systemui' else 'meego-im-uiserv',
                'EXECUTABLE': 'sysuid' if service == 'systemui' else 'meego-im-uiserver',
                'EXECUTABLE_MD5': UI.SYSUID_MD5 if service == 'systemui' else KEYBOARD.LIBRARIES['/usr/bin/meego-im-uiserver']}
            env.pop('N00_UI_POLL_READINESS_FIRST', None)
            if readiness_first is not None:
                env['N00_UI_POLL_READINESS_FIRST'] = readiness_first
            result = subprocess.run(['sh', '-c', prelude + report + '\nif ' + function + '; then :; else exit $?; fi\n'],
                                    env=env, capture_output=True, timeout=5)
            calls = trace.read_text().splitlines() if trace.exists() else []
            return result, calls

    def test_successful_reordered_reports_retain_all_original_hashes(self):
        for service, validator, expected in (
                ('systemui', UI.validate_serial, ['owner', 'pixmap', 'identity', 'hashes']),
                ('ime', KEYBOARD.validate_serial, ['mapping', 'owner', 'address', 'identity', 'hashes'])):
            with self.subTest(service=service):
                result, calls = self.run_report(service, readiness_first='1')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(calls, expected)
                self.assertTrue(validator(result.stdout, minimum_reports=1)['same_instance'])

    def test_default_reports_preserve_original_identity_and_mapping_order(self):
        for service, validator, expected in (
                ('systemui', UI.validate_serial, ['identity', 'hashes', 'owner', 'pixmap']),
                ('ime', KEYBOARD.validate_serial, ['identity', 'hashes', 'mapping', 'owner', 'address'])):
            for readiness_first in (None, '', '0', 'true'):
                with self.subTest(service=service, readiness_first=readiness_first):
                    result, calls = self.run_report(service, readiness_first=readiness_first)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(calls, expected)
                    self.assertTrue(validator(result.stdout, minimum_reports=1)['same_instance'])

    def test_default_unready_reports_keep_identity_before_readiness(self):
        for service, readiness_calls in (
                ('systemui', ['owner', 'pixmap']),
                ('ime', ['mapping', 'owner', 'address'])):
            for index, failure in enumerate(readiness_calls):
                with self.subTest(service=service, failure=failure):
                    result, calls = self.run_report(service, failure=failure)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(calls, ['identity', 'hashes'] + readiness_calls[:index + 1])

    def test_unready_poll_fails_before_hashing(self):
        for service, failures in (('systemui', ('process', 'owner', 'pixmap')),
                                  ('ime', ('process', 'mapping', 'owner', 'address'))):
            for failure in failures:
                with self.subTest(service=service, failure=failure):
                    result, calls = self.run_report(service, failure=failure, readiness_first='1')
                    self.assertNotEqual(result.returncode, 0)
                    self.assertNotIn('hashes', calls)

    def test_disk_wait_and_stopped_process_still_fail(self):
        for service in ('systemui', 'ime'):
            for state in ('D', 'T', 'Z'):
                with self.subTest(service=service, state=state):
                    result, calls = self.run_report(service, state=state, readiness_first='1')
                    self.assertNotEqual(result.returncode, 0)
                    self.assertNotIn('hashes', calls)
                    self.assertEqual(calls.count('sleep 1'), 5 if service == 'ime' else 0)

    def test_reordered_reports_still_reject_replaced_binary_and_wrong_owner(self):
        for service, validator in (('systemui', UI.validate_serial), ('ime', KEYBOARD.validate_serial)):
            for options in ({'bad_hash': True}, {'owner': '999'}):
                with self.subTest(service=service, options=options):
                    result, calls = self.run_report(service, readiness_first='1', **options)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn('hashes', calls)
                    with self.assertRaises(ValueError):
                        validator(result.stdout, minimum_reports=1)

    def test_poll_observations_keep_budgets_and_stay_outside_success_reports(self):
        for service, validator, fixture in (('systemui', UI.validate_serial, systemui_report()),
                                             ('ime', KEYBOARD.validate_serial, ime_report())):
            source = (SCRIPTS / ('diagnose-shell-guest.sh' if service == 'systemui' else 'input-method-guest.sh')).read_text()
            if service == 'systemui':
                start = source.index('        systemui_attempts=')
                snippet = source[start:source.index('\n        ;;', start)]
                function, reason, original_log = 'report_systemui', 'systemui_wait_reason', '/tmp/n00-systemui-ready.log'
            else:
                start = source.index('    ime_ready=0')
                snippet = source[start:source.index('\n}', start)]
                function, reason, original_log = 'report_input_method', 'ime_wait_reason', '/tmp/n00-ime-ready.log'
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / 'fixture').write_bytes(fixture)
                trace = root / 'sleeps'
                snippet = snippet.replace(original_log, str(root / 'report'))
                prelude = ('set -eu\ncount=0\nready=0\n' +
                    'sleep() { printf "sleep\\n" >> ' + shlex.quote(str(trace)) + '; }\n' +
                    'tail() { :; }\n' + function + '() {\n' +
                    'count=$((count + 1))\nime_state_sleeps=2\n' + reason + '=owner\n' +
                    'if [ "$count" -lt "$READY_AT" ]; then printf "FAILED_PARTIAL_REPORT\\n"; return 1; fi\n' +
                    'cat ' + shlex.quote(str(root / 'fixture')) + '\n}\n')
                for ready_at, expected_attempts, expected_sleeps, exit_code in ((3, 3, 2, 0), (16, 15, 15, 1)):
                    with self.subTest(service=service, ready_at=ready_at):
                        trace.write_text('')
                        result = subprocess.run(['sh', '-c', prelude + 'run_poll() {\n' + snippet + '\n}\nrun_poll\n'],
                            env=os.environ | {'READY_AT': str(ready_at), 'N00_UI_SYSTEMUI_ATTEMPTS': '15'},
                            capture_output=True, timeout=5)
                        self.assertEqual(result.returncode, exit_code, result.stderr)
                        self.assertEqual(len(trace.read_text().splitlines()), expected_sleeps)
                        self.assertIn(f'attempts={expected_attempts} budget=15'.encode(), result.stdout)
                        self.assertIn(f'failed_owner={expected_sleeps}'.encode(), result.stdout)
                        if service == 'ime':
                            self.assertIn(f'state_sleeps={expected_attempts * 2}'.encode(), result.stdout)
                        if exit_code == 0:
                            self.assertNotIn(b'FAILED_PARTIAL_REPORT', result.stdout)
                            self.assertTrue(validator(result.stdout, minimum_reports=1)['same_instance'])


if __name__ == '__main__':
    unittest.main()
