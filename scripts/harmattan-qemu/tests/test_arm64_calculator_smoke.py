import hashlib
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CALC = load('calculator_gate', 'smoke-arm64-calculator.py')
SHELL = load('calculator_shell_gate', 'diagnose-arm64-shell.py')
HOME = {'home_window': '00800002', 'wm_window': '00400017', 'pids': {'meegotouchhome': 163}}


def block(stage, pid=235, active=None):
    foreground = '00800002' if stage in ('before', 'returned', 'final') else '00a00002'
    active = active or foreground
    clients = '00800002' if stage == 'before' else '00a00002,00800002' if foreground == '00800002' else '00800002,00a00002'
    lines = [f'N00_CALC_BEGIN_{stage}', CALC.CALC_MD5 + '  /usr/bin/calc',
             '# HARMATTAN_QEMU_DIRECT_INVOKER',
             'N00_X11_WM check=00400017 self=00400017',
             'N00_X11_COMPOSITOR owner=00400017', f'N00_X11_ACTIVE id={active}',
             f'N00_X11_CLIENTS {clients}',
             'N00_X11_WINDOW id=00800002 map=2 geometry=864x480+0+0 pid=163 class=' +
             b'meegotouchhome\0Meegotouchhome\0'.hex()]
    if stage == 'before':
        lines.append('N00_CALCULATOR_PROCESS absent')
    else:
        lines.extend([f'N00_CALCULATOR_PROCESS {pid}', 'Name:\tcalc', 'State:\tS (sleeping)',
                      f'Tgid:\t{pid}', f'Pid:\t{pid}', 'PPid:\t1', 'TracerPid:\t0',
                      'Uid:\t29999\t29999\t29999\t29999', 'Gid:\t29999\t29999\t29999\t29999',
                      '/usr/bin/calc', f'{CALC.CALC_MD5}  /proc/{pid}/exe',
                      f'N00_X11_WINDOW id=00a00002 map=2 geometry=864x480+0+0 pid={pid} class=' +
                      b'calc\0Calc\0'.hex()])
    lines.extend(['N00_X11_INSPECT_OK', f'N00_CALC_EXIT_{stage}_0', '', f'N00_CALC_DONE_{stage}'])
    return ('\n'.join(lines) + '\n').encode()


def serial():
    return b''.join(block(stage) for stage in CALC.STAGES)


def host():
    return (b'N00_GLES connect client=0 abi=1\nN00_GLES connect client=1 abi=2\n'
            b'N00_GLES current client=1 es=2 renderer=Apple Test GPU\n'
            b'N00_GLES connect client=2 abi=2\nN00_GLES current client=2 es=2 renderer=Apple Test GPU\n'
            b'N00_GLES disconnect client=1\nN00_GLES disconnect client=2\nN00_GLES disconnect client=0\n'
            b'N00_GLES render compiles=9 links=6 uploads=171 draws=225 rejects=0\n'
            b'N00_GLES summary calls=7074 swaps=65 faults=0 workers=joined\n')


class CalculatorGateTests(unittest.TestCase):
    def test_complete_original_application_lifecycle(self):
        result = CALC.validate_serial(serial(), HOME)
        self.assertEqual(result['runtime_md5'], CALC.CALC_MD5)
        self.assertEqual(result['pid'], 235)
        self.assertTrue(result['same_instance_resumed'])
        self.assertEqual(result['home_returns'], 2)

    def test_echo_missing_duplicate_and_failed_markers(self):
        for value in (serial().replace(b'N00_CALC_BEGIN_sum\n', b"printf 'N00_CALC_BEGIN_sum'\n"),
                      serial() + block('sum'), serial().replace(b'N00_CALC_EXIT_sum_0', b'N00_CALC_EXIT_sum_1'),
                      b''.join(block(stage) for stage in reversed(CALC.STAGES)),
                      serial().replace(b'N00_X11_INSPECT_OK', b'partial')):
            with self.subTest(value=value[:60]), self.assertRaises(ValueError):
                CALC.validate_serial(value, HOME)

    def test_existing_app_wrong_binary_and_live_executable(self):
        for value in (serial().replace(b'N00_CALCULATOR_PROCESS absent', b'N00_CALCULATOR_PROCESS 235'),
                      serial().replace(CALC.CALC_MD5.encode() + b'  /usr/bin', b'0' * 32 + b'  /usr/bin'),
                      serial().replace(CALC.CALC_MD5.encode() + b'  /proc', b'0' * 32 + b'  /proc'),
                      serial().replace(b'# HARMATTAN_QEMU_DIRECT_INVOKER', b'# original invoker')):
            with self.assertRaises(ValueError):
                CALC.validate_serial(value, HOME)

    def test_stopped_traced_wrong_user_or_duplicate_process(self):
        for value in (serial().replace(b'State:\tS', b'State:\tT'),
                      serial().replace(b'TracerPid:\t0', b'TracerPid:\t55'),
                      serial().replace(b'Uid:\t29999', b'Uid:\t0'),
                      serial().replace(b'Uid:\t29999\t29999', b'Uid:\t29999\t0'),
                      serial().replace(b'N00_CALCULATOR_PROCESS 235', b'N00_CALCULATOR_PROCESS 235 236')):
            with self.assertRaises(ValueError):
                CALC.validate_serial(value, HOME)

    def test_relaunch_cannot_be_called_same_instance_resume(self):
        value = b''.join(block(stage, pid=236 if stage in ('reopened', 'final') else 235) for stage in CALC.STAGES)
        with self.assertRaises(ValueError):
            CALC.validate_serial(value, HOME)

    def test_foreground_and_manager_not_just_process_presence(self):
        for value in (serial().replace(block('returned'), block('returned', active='00a00002')),
                      serial().replace(b'map=2 geometry=864x480', b'map=0 geometry=864x480'),
                      serial().replace(b'self=00400017', b'self=00400018'),
                      serial().replace(b'N00_X11_CLIENTS 00800002,00a00002', b'N00_X11_CLIENTS 00800002')):
            with self.assertRaises(ValueError):
                CALC.validate_serial(value, HOME)

    def test_exact_full_frames_result_and_home_returns(self):
        header = b'P6\n864 480\n255\n'
        raw = [bytes([value]) * (864 * 480 * 3) for value in (1, 2, 5)]
        home_frame, zero, five = [header + data for data in raw]
        frames = {stage: home_frame if stage in ('before', 'returned', 'final') else zero if stage == 'opened' else five
                  for stage in CALC.STAGES}
        # Synthetic unit fixtures exercise gate logic only; the production
        # constants above remain real, visually checked full-frame digests.
        with patch.object(CALC, 'ZERO_RGB', hashlib.sha256(raw[1]).hexdigest()), \
             patch.object(CALC, 'FIVE_RGB', hashlib.sha256(raw[2]).hexdigest()):
            self.assertTrue(CALC.validate_frames(home_frame, frames)['full_frame_matches'])
            for stage in CALC.STAGES:
                with self.subTest(stage=stage), self.assertRaises(ValueError):
                    CALC.validate_frames(home_frame, {**frames, stage: frames[stage][:-1] + b'\x00'})
            with self.assertRaises(ValueError):
                CALC.validate_frames(home_frame, {**frames, 'opened': b''})

    def test_known_warning_is_partial_and_old_gate_still_rejects_it(self):
        warned = host().replace(b'N00_GLES disconnect client=1', CALC.TEXTURE_WARNING + b'\nN00_GLES disconnect client=1')
        result = CALC.inspect_host(warned, SHELL.validate_desktop_host)
        self.assertFalse(result['clean'])
        self.assertEqual(result['warnings'], [CALC.TEXTURE_WARNING.decode()])
        with self.assertRaises(ValueError):
            SHELL.validate_desktop_host(warned)
        self.assertTrue(CALC.inspect_host(host(), SHELL.validate_desktop_host)['clean'])

    def test_unknown_repeated_warnings_faults_or_unjoined_workers_fail(self):
        for value in (host() + b'warning: Blocked re-entrant IO\n',
                      host() + (CALC.TEXTURE_WARNING + b'\n') * 2,
                      host().replace(b'faults=0', b'faults=1'),
                      host().replace(b'rejects=0', b'rejects=1'),
                      host().replace(b'workers=joined', b'workers=pending')):
            with self.assertRaises(ValueError):
                CALC.inspect_host(value, SHELL.validate_desktop_host)

    def test_probe_uses_real_absolute_input_and_releases_contacts(self):
        class QMP:
            def __init__(self): self.commands = []
            def call(self, name, args): self.commands.append((name, args))
        class Serial:
            def __init__(self): self.commands = []
            def sendall(self, data): self.commands.append(data)
        for rotation in (0, 90, 180, 270):
            qmp, channel, checkpoints, captures = QMP(), Serial(), [], []
            with patch.object(CALC.time, 'sleep'), patch('builtins.print'):
                CALC.run_probe(qmp, channel, checkpoints.append, captures.append, SHELL.display, rotation)
            self.assertEqual(captures, ['calculator-' + stage for stage in CALC.STAGES])
            self.assertEqual(len(channel.commands), 6)
            for stage, command in zip(CALC.STAGES, channel.commands):
                self.assertIn(f'calculator-inspect {stage}'.encode(), command)
            self.assertEqual(len(qmp.commands), 56)
            self.assertEqual(sum(not args['events'][-1]['data']['down'] for _, args in qmp.commands), 8)
            for name, args in qmp.commands:
                self.assertEqual(name, 'input-send-event')
                self.assertEqual([event['type'] for event in args['events']], ['abs', 'abs', 'btn'])
                self.assertTrue(all(0 <= event['data']['value'] <= 32767 for event in args['events'][:2]))
            self.assertFalse(qmp.commands[-1][1]['events'][-1]['data']['down'])

    def test_dynamic_statusbar_does_not_weaken_home_content_round_trip(self):
        header = b'P6\n864 480\n255\n'
        raw = [bytes([value]) * (864 * 480 * 3) for value in (1, 2, 5)]
        home_frame, zero, five = [header + data for data in raw]
        changed_home = bytearray(home_frame)
        changed_home[len(header) + 3] ^= 1
        frames = {stage: bytes(changed_home) if stage in ('returned', 'final') else home_frame if stage == 'before'
                  else zero if stage == 'opened' else five for stage in CALC.STAGES}
        with patch.object(CALC, 'ZERO_RGB', hashlib.sha256(raw[1]).hexdigest()), \
             patch.object(CALC, 'FIVE_RGB', hashlib.sha256(raw[2]).hexdigest()):
            result = CALC.validate_frames(home_frame, frames, allow_statusbar_change=True,
                                          expect_statusbar_change=True)
            self.assertTrue(result['home_content_matches'])
            self.assertEqual(result['statusbar_changed_pixels']['returned'], 1)
            unchanged = {**frames, 'returned': home_frame, 'final': home_frame}
            with self.assertRaises(ValueError):
                CALC.validate_frames(home_frame, unchanged, True, True)
            outside = bytearray(changed_home)
            outside[len(header) + 72 * 3 + 3] ^= 1
            with self.assertRaises(ValueError):
                CALC.validate_frames(home_frame, {**frames, 'returned': bytes(outside)}, True, True)


if __name__ == '__main__':
    unittest.main()
