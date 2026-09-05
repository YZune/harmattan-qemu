from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location('guest_clock', ROOT / 'scripts/harmattan-qemu/arm64-clock.py')
CLOCK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLOCK)


ZONE = b'TZif2' + b'\0' * 80
ZONE_MD5 = hashlib.md5(ZONE).hexdigest()
BASE = 1788544980
LOCAL_ZONE = timezone(timedelta(hours=8))


def local(epoch):
    return datetime.fromtimestamp(epoch, LOCAL_ZONE).strftime('%Y-%m-%dT%H:%M:%S%z')


def heartbeat(dsme_pid=41, server_pid=42):
    lines = ['N00_HEARTBEAT_REPORT_BEGIN']
    for name, pid, path in (('dsme', dsme_pid, '/sbin/dsme'),
                            ('dsme-server', server_pid, '/sbin/dsme-server')):
        lines.extend([f'N00_HEARTBEAT_PROCESS {name} {pid}', f'Name:\t{name}', 'State:\tS (sleeping)',
                      f'Tgid:\t{pid}', f'Pid:\t{pid}', 'PPid:\t1', 'TracerPid:\t0',
                      'Uid:\t0\t0\t0\t0', 'Gid:\t0\t0\t0\t0', path,
                      f'{CLOCK.HEARTBEAT_MD5[path]}  /proc/{pid}/exe'])
    lines.extend(f'{digest}  {path}' for path, digest in CLOCK.HEARTBEAT_MD5.items())
    lines.extend(['N00_HEARTBEAT_SOCKET_READY /dev/shm/iphb',
                  'N00_HEARTBEAT_KERNEL_DEVICE_READY /dev/iphb', 'N00_HEARTBEAT_REPORT_END'])
    return lines


def serial(epochs=None, digest=ZONE_MD5, rtc='absent', additional=()):
    epochs = epochs or [BASE + value for value in (0, 1, 8, 34, 39, 40)]
    lines = [f'N00_CLOCK_SYNC source=host utc_epoch={BASE} local={local(BASE)} offset=+0800 zone_md5={digest} rtc={rtc}',
             'N00_CLOCK_SYNC_EXIT_0', 'N00_CLOCK_SYNC_FINISHED', *heartbeat()]
    for phase, epoch in zip(CLOCK.REPORT_PHASES, epochs):
        lines.append(f'N00_CLOCK_REPORT phase={phase} utc_epoch={epoch} local={local(epoch)} offset=+0800 zone_md5={digest} heartbeat=41,42')
    for phase, epoch in additional:
        lines.append(f'N00_CLOCK_REPORT phase={phase} utc_epoch={epoch} local={local(epoch)} offset=+0800 zone_md5={digest} heartbeat=41,42')
    if additional:
        lines.extend(['N00_HEARTBEAT_RUNTIME_BEGIN', 'DSME 0.63.0 starting up',
                      'DSME debug: heartbeat.so loaded', 'DSME debug: iphb.so loaded',
                      'DSME debug: HEARTBEAT from HWWD',
                      'DSME debug: client with PID 53 (sysuid) signaled interest of waiting (min=12/max=13)',
                      'DSME debug: waking up clients because somebody was woken up',
                      'DSME debug: HEARTBEAT from HWWD',
                      'DSME debug: client with PID 53 (sysuid) signaled interest of waiting (min=59/max=60)',
                      'N00_HEARTBEAT_RUNTIME_END'])
    return ('\n'.join(lines) + '\n').encode()


class GuestClockTests(unittest.TestCase):
    def test_modes_are_explicit(self):
        self.assertTrue(CLOCK.enabled('host'))
        self.assertFalse(CLOCK.enabled('off'))
        with self.assertRaises(ValueError):
            CLOCK.enabled('local')

    def test_timezone_payload_is_bounded_tzif(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'zoneinfo'
            path.write_bytes(ZONE)
            payload, metadata = CLOCK.prepare(path)
            self.assertEqual(payload, ZONE)
            self.assertEqual(metadata['timezone_md5'], ZONE_MD5)
            for bad in (b'', b'not-a-timezone', b'TZif'):
                path.write_bytes(bad)
                with self.assertRaises(ValueError):
                    CLOCK.prepare(path)

    def test_utc_snapshot_builds_busybox_setting_command(self):
        value = CLOCK.snapshot(datetime(2026, 9, 4, 18, 3, 0, tzinfo=timezone.utc))
        self.assertEqual(value, {'epoch': BASE, 'utc': '2026-09-04T18:03:00Z',
                                 'date_argument': '090418032026.00'})
        command = CLOCK.guest_sync_command(value, ZONE_MD5)
        self.assertIn(b'date -u 090418032026.00', command)
        self.assertIn(b'export N00_UI_CLOCK_SYNC=1', command)
        with self.assertRaises(ValueError):
            CLOCK.snapshot(datetime(2026, 9, 4, 18, 3, 0))

    def test_phase_clock_stays_aligned_and_local_time_maps_to_epoch(self):
        result = CLOCK.validate_serial(serial(), BASE, ZONE_MD5, now_epoch=BASE + 42)
        self.assertEqual(result['reports'], 6)
        self.assertEqual(result['elapsed_seconds'], 40)
        self.assertEqual(result['utc_offset_at_sync'], '+0800')
        self.assertEqual(result['rtc'], 'absent')
        self.assertEqual(result['heartbeat']['server_pid'], 42)

    def test_missing_duplicate_wrong_digest_or_failed_sync_is_rejected(self):
        valid = serial()
        for data in (valid.replace(b'N00_CLOCK_SYNC_FINISHED\n', b''),
                     valid + b'N00_CLOCK_SYNC_FINISHED\n',
                     valid.replace(b'N00_CLOCK_SYNC_EXIT_0', b'N00_CLOCK_SYNC_EXIT_1'),
                     serial(digest='0' * 32),
                     valid.replace(b'phase=theme', b'phase=bootstrap'),
                     valid.replace(b'N00_HEARTBEAT_SOCKET_READY', b'N00_HEARTBEAT_SOCKET_MISSING'),
                     valid.replace(b'heartbeat=41,42', b'heartbeat=41,43')):
            with self.subTest(data=data[-80:]), self.assertRaises(ValueError):
                CLOCK.validate_serial(data, BASE, ZONE_MD5, now_epoch=BASE + 42)

    def test_backwards_stopped_or_mislabeled_local_clock_is_rejected(self):
        cases = [
            (serial([BASE, BASE + 1, BASE + 8, BASE + 34, BASE + 33, BASE + 40]), BASE + 42),
            (serial(), BASE + 100),
            (serial().replace(local(BASE + 34).encode(), local(BASE + 35).encode()), BASE + 42),
            (serial().replace(b'offset=+0800', b'offset=+0700', 1), BASE + 42),
        ]
        for data, now in cases:
            with self.subTest(now=now), self.assertRaises(ValueError):
                CLOCK.validate_serial(data, BASE, ZONE_MD5, now_epoch=now)

    def test_additional_app_reports_prove_minute_progression(self):
        phases = tuple(f'calculator-{stage}' for stage in ('before', 'opened', 'sum', 'returned', 'reopened', 'final'))
        extra = tuple(zip(phases, (BASE + 41, BASE + 56, BASE + 61, BASE + 71, BASE + 79, BASE + 87)))
        result = CLOCK.validate_serial(serial(additional=extra), BASE, ZONE_MD5,
                                       now_epoch=BASE + 88, additional_phases=phases)
        self.assertTrue(result['minute_changed_after_home'])
        self.assertEqual(result['local_minutes']['calculator-final'], local(BASE + 87)[:16])
        self.assertTrue(result['heartbeat']['runtime_trace']['rearmed_after_wakeup'])
        valid = serial(additional=extra)
        for corrupted in (valid.replace(b'N00_HEARTBEAT_RUNTIME_BEGIN', b'N00_HEARTBEAT_RUNTIME_MISSING'),
                          valid.replace(b'heartbeat.so loaded', b'heartbeat.so absent'),
                          valid.replace(b'waking up clients because somebody was woken up', b'no wakeup'),
                          valid.replace(b'(min=59/max=60)', b'(min=12/max=13)\ndsme-server nonresponsive')):
            with self.assertRaises(ValueError):
                CLOCK.validate_serial(corrupted, BASE, ZONE_MD5, now_epoch=BASE + 88,
                                      additional_phases=phases)

    def test_launcher_clock_defaults_preserve_historical_diagnostics(self):
        launcher = (ROOT / 'scripts/harmattan-qemu/run-arm64-ui.sh').read_text()
        start = launcher.index('\nclock=${HARMATTAN_UI_CLOCK:-}') + 1
        block = launcher[start:launcher.index('\nif [ "$mode" = interactive ]', start)]

        def selected(mode, override=None):
            environment = {'PATH': '/usr/bin:/bin'}
            if override is not None:
                environment['HARMATTAN_UI_CLOCK'] = override
            result = subprocess.run(
                ['/bin/sh', '-eu', '-c', 'mode=$1\n' + block + '\nprintf "%s" "$clock"',
                 'clock-selection', mode], env=environment, capture_output=True, text=True,
                timeout=3, check=True)
            return result.stdout

        for mode in ('interactive', '--gpu-headless-diagnostic', '--animation-diagnostic',
                     '--startup-input-headless-diagnostic', '--usability-headless-diagnostic'):
            self.assertEqual(selected(mode), 'host')
        for mode in ('--calculator-diagnostic', '--orientation-headless-diagnostic',
                     '--performance-diagnostic', '--smoke'):
            self.assertEqual(selected(mode), 'off')
        self.assertEqual(selected('--smoke', 'host'), 'host')
        self.assertEqual(selected('interactive', 'off'), 'off')

    def test_home_content_comparison_scopes_dynamic_statusbar(self):
        size = len(CLOCK.PPM_HEADER) + 864 * 480 * 3
        first = CLOCK.PPM_HEADER + b'\0' * (size - len(CLOCK.PPM_HEADER))
        changed = bytearray(first)
        changed[len(CLOCK.PPM_HEADER) + 7] = 1
        result = CLOCK.compare_home_frames(first, bytes(changed), allow_statusbar_change=True)
        self.assertTrue(result['content_equal'])
        self.assertEqual(result['statusbar_changed_pixels'], 1)
        changed[len(CLOCK.PPM_HEADER) + CLOCK.STATUSBAR_THICKNESS * 3 + 7] = 1
        self.assertFalse(CLOCK.compare_home_frames(first, bytes(changed), True)['content_equal'])
        self.assertFalse(CLOCK.compare_home_frames(first, bytes(changed), False)['content_equal'])


if __name__ == '__main__':
    unittest.main()
