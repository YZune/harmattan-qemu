"""Original sysuid lock UI controlled by the Cocoa side key, without MCE."""
import json
import os
from pathlib import Path
import re
import stat


def payloads():
    scripts = Path(__file__).parent
    return {name: (scripts / name).read_bytes() for name in ('N00X11.pm', 'screenlock-guest.pl')}


def parse_report(data, pid=None):
    reports = re.findall(rb'^N00_LOCKSCREEN window=([0-9a-f]{8}) pid=([1-9][0-9]*) mapped=([01]) low_power=([01])$', data, re.M)
    if len(reports) != 1:
        raise ValueError('Missing or ambiguous original lock UI state')
    window, actual, mapped, low = reports[0]
    result = dict(window=int(window, 16), pid=int(actual), mapped=bool(int(mapped)), low_power=bool(int(low)))
    if pid is not None and result['pid'] != pid:
        raise ValueError('Original lock UI process changed')
    if not result['window'] and (result['mapped'] or result['low_power']):
        raise ValueError('Lock UI state without a window')
    return result


class Control:
    def __init__(self, output):
        self.output = output
        self.directory = output / 'lockscreen'
        self.directory.mkdir(mode=0o700)
        self.sequence = 0
        self.pid = None
        self.info = {'enabled': True, 'original_ui': True, 'hardware_suspend': False,
                     'device_security_lock': False, 'actions': []}

    def environment(self):
        return {'N00_COCOA_LOCKSCREEN': str(self.directory)}

    def enable(self):
        with (self.directory / 'ready').open('xb') as stream:
            stream.write(b'ready\n')

    def close(self):
        (self.directory / 'ready').unlink(missing_ok=True)

    def pending(self):
        path = self.directory / 'request'
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            return False
        try:
            metadata = os.fstat(fd)
            if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid()
                    or metadata.st_size != 6 or os.read(fd, 7) != b'press\n'):
                raise ValueError('Invalid side-key request')
        finally:
            os.close(fd)
        return True

    def phase(self, serial, wait_line, action):
        if action not in ('inspect', 'press'):
            raise ValueError('Invalid lock UI action')
        self.sequence += 1
        marker = f'N00_LOCK_PHASE_{self.sequence}'
        serial.sendall((f"printf '\\n{marker}_BEGIN\\n'; "
            f"perl /tmp/n00-ui-helpers/screenlock-guest.pl {action}; "
            f"printf '{marker}_EXIT_%s\\n' $?; printf '{marker}_DONE\\n'\n").encode())
        wait_line((marker + '_DONE').encode())
        raw = (self.output / 'serial.log').read_bytes().replace(b'\r', b'')
        blocks = re.findall(rb'^' + marker.encode() + rb'_BEGIN\n(.*?)^' + marker.encode() + rb'_EXIT_(\d+)\n', raw, re.M | re.S)
        if len(blocks) != 1 or blocks[0][1] != b'0':
            raise ValueError('Original lock UI action failed; inspect serial.log')
        result = parse_report(blocks[0][0], self.pid)
        self.pid = result['pid']
        self.info['actions'].append(dict(action=action, **result))
        (self.directory / 'state.json').write_text(json.dumps(self.info, indent=2) + '\n')
        return result

    def consume(self, serial, wait_line):
        result = self.phase(serial, wait_line, 'press')
        (self.directory / 'request').unlink()
        return result


def run_probe(control, qmp, serial, wait_line, capture, drain, calculator, display, home):
    """Guest input and original window state; physical Cocoa input is separate."""
    def pointer(x, y, down):
        qmp.call('input-send-event', {'events': [
            {'type': 'abs', 'data': {'axis': 'x', 'value': round(x * 32767 / 479)}},
            {'type': 'abs', 'data': {'axis': 'y', 'value': round(y * 32767 / 863)}},
            {'type': 'btn', 'data': {'button': 'left', 'down': down}}]})

    def swipe(end):
        pointer(2, 440, True)
        for i in range(1, 21):
            drain(.04)
            pointer(2 + (end - 2) * i / 20, 440, True)
        pointer(end, 440, False)
        drain(1)

    def inspect(mapped, low=None):
        result = control.phase(serial, wait_line, 'inspect')
        if result['mapped'] != mapped or (low is not None and result['low_power'] != low):
            raise ValueError('Unexpected original lock state during input regression')

    def press():
        # Exercise the same mailbox/consumer as Cocoa, including coalescing.
        (control.directory / 'request').write_bytes(b'press\n')
        if not control.pending():
            raise ValueError('Missing side-key request')
        control.consume(serial, wait_line)
        drain(1)

    inspect(False)
    press()
    inspect(True, True)
    capture('lockscreen-clock')
    swipe(460)
    inspect(True, True)
    press()
    inspect(True, False)
    capture('lockscreen-wallpaper')
    pointer(240, 440, True)
    drain(.1)
    pointer(240, 440, False)
    drain(.5)
    inspect(True, False)
    swipe(70)
    inspect(True, False)
    swipe(460)
    inspect(False)
    capture('lockscreen-unlocked')
    # Repeat across the already-created original window and updated mode.
    press()
    inspect(True, True)
    press()
    inspect(True, False)
    swipe(460)
    inspect(False)
    def raw(name):
        return display.native_ppm((control.output / (name + '.ppm')).read_bytes(), 270)

    def calculator_capture(name):
        capture(name)
        if name == 'calculator-sum':
            press()
            inspect(True, True)
            press()
            inspect(True, False)
            swipe(460)
            inspect(False)
            drain(2)
            capture('lockscreen-calculator-resumed')
            if raw(name) != raw('lockscreen-calculator-resumed'):
                raise ValueError('Calculator pixels changed across lock/unlock')

    # Unlock activity briefly reveals Home's original scrollbar. Let its
    # normal fade finish before the exact-pixel Calculator/Home regression.
    drain(6)
    calculator.run_probe(qmp, serial, wait_line, calculator_capture, display, 270)
    control.info['calculator'] = calculator.validate_serial((control.output / 'serial.log').read_bytes(), home)
    control.info['calculator_frames'] = calculator.validate_frames(raw('settled'),
        {stage: raw('calculator-' + stage) for stage in calculator.STAGES}, allow_statusbar_change=True)
    control.info['calculator_pixels_restored'] = True
    control.info['guest_input_passed'] = True
