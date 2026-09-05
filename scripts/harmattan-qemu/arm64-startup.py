"""Startup input barrier: strict original Home checks precede input release."""
import hashlib
from pathlib import Path
import re
import time

FILES = ('N00X11.pm', 'startup-input-guest.pl')
BASE = '/tmp/n00-startup-input'


def prepare():
    scripts = Path(__file__).resolve().parent
    payloads = {name: (scripts / name).read_bytes() for name in FILES}
    return payloads, {'files': {name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()},
                      'controller_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def validate(log, released=False, exercised=False):
    lines = log.replace(b'\r', b'').splitlines()
    if not lines:
        raise ValueError('missing startup input barrier')
    held = re.fullmatch(rb'N00_STARTUP_INPUT_HELD pid=([1-9][0-9]*)', lines[0])
    if not held:
        raise ValueError('input barrier did not acquire both grabs')
    pid = held[1]
    expected = ('home', 'settled', 'final')
    counts = []
    for index, tag in enumerate(expected, 1):
        if len(lines) <= index:
            raise ValueError('startup barrier observation missing')
        match = re.fullmatch(rb'N00_STARTUP_INPUT_CHECK tag=' + tag.encode() + rb' pid=' + pid +
                             rb' buttons=(\d+) keys=(\d+) motions=(\d+)', lines[index])
        if not match:
            raise ValueError('startup barrier failed, restarted or released early')
        counts.append(tuple(map(int, match.groups())))
    if any(any(a > b for a, b in zip(before, after)) for before, after in zip(counts, counts[1:])):
        raise ValueError('startup input counters went backwards')
    if exercised and counts[-1][0] < 4:
        raise ValueError('early clicks did not reach the real X11 input barrier')
    if not released:
        if len(lines) != 4:
            raise ValueError('input released before startup verification')
    else:
        if len(lines) != 6 or lines[4] != b'N00_STARTUP_INPUT_RELEASE_REQUEST pid=' + pid:
            raise ValueError('missing unique startup release request')
        match = re.fullmatch(rb'N00_STARTUP_INPUT_RELEASED pid=' + pid + rb' buttons=(\d+) keys=(\d+) motions=(\d+)', lines[5])
        if not match or any(a > b for a, b in zip(counts[-1], map(int, match.groups()))):
            raise ValueError('startup barrier release was not acknowledged')
    return {'pid': int(pid), 'released': released, 'early_button_events': counts[-1][0],
            'scope': 'guest X11 input discarded until strict startup verification; not host cursor capture'}


def inject_early_clicks(qmp):
    # Native portrait Calculator icon, same MXT path as the normal app probe.
    for _ in range(2):
        for down in (True, False):
            qmp.call('input-send-event', {'events': [
                {'type': 'abs', 'data': {'axis': 'x', 'value': round(183 * 32767 / 479)}},
                {'type': 'abs', 'data': {'axis': 'y', 'value': round(692 * 32767 / 863)}},
                {'type': 'btn', 'data': {'button': 'left', 'down': down}}]})
            time.sleep(0.15)


def collect(serial, wait_line, out, release=False):
    tag = 'released' if release else 'held'
    command = 'startup-release' if release else 'startup-inspect'
    serial.sendall((f"printf '\\nN00_STARTUP_{tag}_BEGIN\\n'; sh /tmp/n00-shell-guest.sh {command}; "
                    f"printf '\\nN00_STARTUP_{tag}_EXIT_%s\\n' $?; printf '\\nN00_STARTUP_{tag}_DONE\\n'\n").encode())
    wait_line(f'N00_STARTUP_{tag}_DONE'.encode())
    data = (out / 'serial.log').read_bytes().replace(b'\r', b'')
    if re.findall(rb'^N00_STARTUP_' + tag.encode() + rb'_EXIT_(\d+)$', data, re.M) != [b'0']:
        raise ValueError('startup input guard command failed')
    blocks = re.findall(rb'(?:^|\n)N00_STARTUP_' + tag.encode() + rb'_BEGIN\n(.*?)\nN00_STARTUP_' + tag.encode() + rb'_EXIT_0', data, re.S)
    if len(blocks) != 1:
        raise ValueError('missing unique startup input report')
    return blocks[0]
