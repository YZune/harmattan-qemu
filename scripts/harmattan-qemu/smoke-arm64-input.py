#!/usr/bin/env python3
"""Exercise QEMU ABS/button -> original MXT driver -> real ARM32 evdev."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import socket
import subprocess
import time

SPEC = importlib.util.spec_from_file_location('display', Path(__file__).with_name('smoke-arm64-display.py'))
display = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(display)
POINTS = ((8192, 8192, True), (0, 0, True), (32767, 32767, True),
          (24576, 16384, True), (24576, 16384, False))


def validate_input_serial(data):
    data = data.replace(b'\r', b'')
    lines = data.split(b'\n')[:-1]
    for marker in (b'N00_INPUT_READER_READY', b'N00_INPUT_RELEASED',
                   b'N00_INPUT_READ_OK', b'N00_INPUT_EXIT_0', b'N00_INPUT_IRQ_DONE'):
        if lines.count(marker) != 1:
            raise ValueError('missing or repeated input checkpoint')
    if any(word in data for word in (b'N00_INPUT_MISSING', b'input packet timeout',
                                    b'short ARM32 input_event', b'Kernel panic', b'Internal error: Oops')):
        raise ValueError('input or kernel failure')
    if re.findall(rb'^N00_INPUT_EXIT_(\d+)$', data, re.MULTILINE) != [b'0']:
        raise ValueError('input reader failed')
    order = [data.index(marker) for marker in (b'\nN00_INPUT_READER_READY\n', b'\nN00_INPUT_EVENT ',
             b'\nN00_INPUT_RELEASED\n', b'\nN00_INPUT_READ_OK\n', b'\nN00_INPUT_EXIT_0\n', b'\nN00_INPUT_IRQ_DONE\n')]
    if order != sorted(order):
        raise ValueError('input checkpoint order mismatch')
    devices = re.findall(rb'^N00_INPUT_DEVICE (/dev/input/event\d+) Atmel mXT Touchscreen$', data, re.MULTILINE)
    if len(devices) != 1 or b'/i2c-2/2-004b/input/input' not in data:
        raise ValueError('missing original I2C MXT device')
    axes = re.findall(rb'^N00_INPUT_ABS (\d+) ([0-9,-]+)$', data, re.MULTILINE)
    if axes != [(b'48', b'0,0,863,0,0,0'), (b'50', b'0,0,0,0,0,0'),
                (b'53', b'0,0,863,0,0,0'), (b'54', b'0,0,479,0,0,0'),
                (b'57', b'0,0,9,0,0,0')]:
        raise ValueError('unexpected touch axis ranges')
    samples = [(215, 119), (0, 0), (863, 479), (646, 239)]
    expected = []
    for index, (x, y) in enumerate(samples):
        packet = [(1, 330, 1)] if index == 0 else []
        packet += [(3, 0, x), (3, 1, y), (3, 53, x), (3, 54, y),
                   (3, 48, 1), (3, 57, 0), (0, 2, 0), (0, 0, 0)]
        expected.append(packet)
    # The original driver reports the released contact once more before BTN_TOUCH=0.
    expected += [[(3, 53, 646), (3, 54, 239), (3, 48, 1), (3, 57, 0), (0, 2, 0), (0, 0, 0)],
                 [(1, 330, 0), (0, 0, 0)]]
    packets, packet, previous = [], [], (-1, -1)
    for line in lines:
        if line.startswith(b'N00_INPUT_EVENT '):
            match = re.fullmatch(rb'N00_INPUT_EVENT (\d+)\.(\d+) (\d+) (\d+) (-?\d+)', line)
            if not match:
                raise ValueError('malformed ARM32 event')
            sec, usec, kind, code, value = map(int, match.groups())
            if usec >= 1000000 or (sec, usec) < previous:
                raise ValueError('invalid event timestamp sequence')
            previous = sec, usec
            packet.append((kind, code, value))
        elif line.startswith(b'N00_INPUT_PACKET_'):
            if line != f'N00_INPUT_PACKET_{len(packets) + 1}'.encode():
                raise ValueError('input packet order mismatch')
            packets.append(packet)
            packet = []
    if packet or packets != expected:
        raise ValueError('down/move/corners/release evdev records differ')
    irqs = re.findall(rb'^\s*221:\s+(\d+)\s+GPIO\s+atmel_mxt$', data, re.MULTILINE)
    if len(irqs) != 1 or int(irqs[0]) < 6:
        raise ValueError('missing real MXT GPIO interrupt activity')
    return {'device': devices[0].decode(), 'packets': len(packets),
            'coordinates': samples, 'released': True, 'gpio_irq': 221,
            'gpio_interrupts': int(irqs[0]), 'range': [863, 479]}


def validate_input_host(data, exit_code):
    if exit_code != 0 or data != b'N00_GLES summary calls=0 swaps=0 faults=0 workers=joined\n':
        raise ValueError('unexpected host error, graphics calls or incomplete shutdown')


def input_events(x, y, down):
    return {'events': [
        {'type': 'abs', 'data': {'axis': 'x', 'value': x}},
        {'type': 'abs', 'data': {'axis': 'y', 'value': y}},
        {'type': 'btn', 'data': {'button': 'left', 'down': down}},
    ]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--timeout', type=float, default=120)
    parser.add_argument('--rotation', type=int, choices=(0, 90, 180, 270), default=0)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    if not command or '-snapshot' not in command or args.timeout <= 0:
        parser.error('a positive timeout and QEMU -snapshot are required')
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    guest = Path(__file__).with_name('inspect-input-guest.pl').read_bytes()
    qemu_digest = hashlib.sha256(Path(command[0]).read_bytes()).hexdigest()
    runner_digest = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    started = time.monotonic()
    deadline = started + args.timeout
    serial, child = socket.socketpair()
    process = None
    try:
        with (out / 'serial.log').open('xb') as log, (out / 'qemu-stderr.log').open('xb') as errors:
            process = subprocess.Popen(command + ['-qmp', 'stdio', '-chardev',
                f'socket,id=n00serial,fd={child.fileno()}', '-serial', 'chardev:n00serial', '-monitor', 'none'],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors,
                env=display.qemu_environment(), pass_fds=(child.fileno(),), bufsize=0)
            child.close()
            qmp = display.QMP(process, deadline)

            def wait_line(marker):
                if marker in (out / 'serial.log').read_bytes().replace(b'\r', b'').split(b'\n')[:-1]:
                    return
                display.wait_serial(serial, process, log,
                    lambda data: marker in data.split(b'\n')[:-1] or b'N00_INPUT_MISSING' in data.split(b'\n')[:-1], deadline)
                if b'N00_INPUT_MISSING' in (out / 'serial.log').read_bytes().replace(b'\r', b'').split(b'\n'):
                    raise RuntimeError('MXT did not register an evdev device; inspect serial.log')

            display.wait_serial(serial, process, log,
                lambda data: b'shell ready' in data and b'/ # ' in data, deadline)
            serial.sendall(b"dmesg -n 1; stty -echo; PS2=''; printf '\\nN00_INPUT_UPLOAD_READY\\n'\n")
            wait_line(b'N00_INPUT_UPLOAD_READY')
            serial.sendall(b"/usr/bin/perl -ne 'chomp; print pack(\"H*\",$_)' > /tmp/n00-input.pl <<'N00_INPUT_SCRIPT'\n")
            encoded = guest.hex()
            for start in range(0, len(encoded), 76):
                serial.sendall(encoded[start:start + 76].encode() + b'\n')
            serial.sendall(b"N00_INPUT_SCRIPT\ncat /proc/bus/input/devices; found=0; "
                b"for event in /sys/class/input/event*; do "
                b"if [ \"$(cat \"$event/device/name\" 2>/dev/null)\" = 'Atmel mXT Touchscreen' ]; then "
                b"found=1; node=/dev/input/${event##*/}; mkdir -p /dev/input; "
                b"[ -c \"$node\" ] || mknod \"$node\" c \"$(cut -d: -f1 \"$event/dev\")\" \"$(cut -d: -f2 \"$event/dev\")\"; "
                b"perl /tmp/n00-input.pl \"$node\" release; printf '\\nN00_INPUT_EXIT_%s\\n' $?; break; fi; done; "
                b"if [ \"$found\" = 0 ]; then ls -l /sys/bus/i2c/devices; cat /proc/interrupts; "
                b"dmesg | tail -80; printf '\\nN00_INPUT_MISSING\\n'; fi\n")
            wait_line(b'N00_INPUT_READER_READY')
            for index, (x, y, down) in enumerate(POINTS, 1):
                x, y = display.surface_point(x, y, args.rotation, 32768, 32768)
                qmp.call('input-send-event', input_events(x, y, down))
                wait_line(f'N00_INPUT_PACKET_{index}'.encode() if down else b'N00_INPUT_RELEASED')
            wait_line(b'N00_INPUT_EXIT_0')
            serial.sendall(b"cat /proc/interrupts; printf '\\nN00_INPUT_IRQ_DONE\\n'\n")
            wait_line(b'N00_INPUT_IRQ_DONE')
            qmp.call('quit')
            process.wait(timeout=5)
            result = {'scope': 'input capture; result.json requires exact event assertions', 'command': command,
                'rotation': args.rotation,
                'qemu_exit': process.returncode,
                'qemu_sha256': qemu_digest,
                'guest_sha256': hashlib.sha256(guest).hexdigest(),
                'wall_seconds': round(time.monotonic() - started, 3)}
            (out / 'diagnostic.json').write_text(json.dumps(result, indent=2) + '\n')
            guest_result = validate_input_serial((out / 'serial.log').read_bytes())
            validate_input_host((out / 'qemu-stderr.log').read_bytes(), process.returncode)
            result.update(passed=True, scope='real single-touch evdev down/move/corners/release; not UI or multitouch acceptance',
                          guest=guest_result, runner_sha256=runner_digest)
            (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
            print(f'PASS: real MXT evdev input including corners and release; evidence: {out}', flush=True)
    finally:
        serial.close(); child.close()
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=5)
            process.stdin.close(); process.stdout.close()


if __name__ == '__main__':
    main()
