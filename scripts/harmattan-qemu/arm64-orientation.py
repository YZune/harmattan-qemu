"""Snapshot-local ContextKit pose and bounded original Calendar regression."""
import hashlib
import os
from pathlib import Path
import re
import subprocess
import time

EDGES = {0: 'top', 90: 'right', 180: 'bottom', 270: 'left'}
REGISTRY = {
    '/usr/share/contextkit/providers/com.nokia.SensorService.context': '48218a843adcf59cc7c1a39d263415b3',
    '/usr/share/contextkit/providers/cache.cdb': 'e6053d11ed0ccaad5642a564675e3a94',
}
STAGES = ('portrait', 'landscape', 'restored', 'calendar', 'calendarlandscape', 'calendarrestored', 'home')
CALENDAR_MD5 = 'd2b9cf2d3f3d13aa909345bebf86c6f5'


def select_edge(mode, interactive, rotation):
    if rotation not in EDGES:
        raise ValueError('invalid display rotation')
    mode = mode or ('display' if interactive else 'disabled')
    if mode == 'disabled':
        return None
    if mode == 'display':
        return EDGES[rotation]
    if mode not in EDGES.values():
        raise ValueError('invalid virtual orientation')
    return mode


def prepare():
    scripts = Path(__file__).resolve().parent
    subprocess.run(['sh', str(scripts / 'build-orientation-guest.sh')], check=True)
    work = Path(os.environ.get('HARMATTAN_PORT_WORKSPACE', scripts.parents[1] / 'extracted/qemu-arm64-port'))
    binary = (work / 'orientation-guest/n00-orientation-provider').read_bytes()
    # ELF32, little-endian, executable, ARM; the loader is original /lib/ld-linux.so.3.
    if len(binary) < 52 or binary[:7] != b'\x7fELF\x01\x01\x01' or binary[16:20] != b'\x02\x00\x28\x00':
        raise ValueError('orientation helper is not an ARM ELF32 executable')
    script = (scripts / 'orientation-guest.sh').read_bytes()
    info = {'helper_sha256': hashlib.sha256(binary).hexdigest(),
            'helper_md5': hashlib.md5(binary).hexdigest(),
            'guest_script_sha256': hashlib.sha256(script).hexdigest(),
            'source_sha256': hashlib.sha256((scripts / 'orientation-provider-guest.c').read_bytes()).hexdigest(),
            'controller_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    return binary, script, info


def block(data, tag):
    data = data.replace(b'\r', b'')
    begin, end = f'N00_POSE_BEGIN_{tag}'.encode(), f'N00_POSE_DONE_{tag}'.encode()
    lines = data.split(b'\n')[:-1]
    if lines.count(begin) != 1 or lines.count(end) != 1:
        raise ValueError('missing or duplicate orientation observation')
    matches = re.findall(rb'(?:^|\n)' + begin + rb'\n(.*?)\n' + end + rb'\n', data, re.S)
    if len(matches) != 1 or re.findall(rb'^N00_POSE_EXIT_' + tag.encode() + rb'_(\d+)$', matches[0], re.M) != [b'0']:
        raise ValueError('orientation command failed or observation is incomplete')
    return matches[0]


def unique(pattern, data):
    values = re.findall(pattern, data, re.M)
    if len(values) != 1:
        raise ValueError('missing or ambiguous orientation identity/value')
    return values[0]


def validate_provider(data, edge, md5):
    lines = data.split(b'\n')
    for marker in (f'N00_ORIENTATION_EXPECT edge={edge} provider=org.harmattan.QemuOrientation',
                   f'N00_ORIENTATION_READY {edge}'):
        if lines.count(marker.encode()) != 1:
            raise ValueError('wrong virtual pose or provider')
    for label, expected in (('TOP_EDGE', b'string "' + edge.encode() + b'"'), ('IS_FLAT', b'boolean false')):
        replies = re.findall(rb'(?:^|\n)N00_ORIENTATION_' + label.encode() + rb'_BEGIN\n(.*?)\nN00_ORIENTATION_' + label.encode() + rb'_END\n', data, re.S)
        if len(replies) != 1:
            raise ValueError('missing ContextKit reply')
        reply = replies[0]
        if re.findall(rb'^\s*variant\s+([^\n]+)$', reply, re.M) != [expected] or not re.search(rb'^\s*uint64 \d+$', reply, re.M):
            raise ValueError('unexpected ContextKit property value')
    pid = unique(rb'^N00_ORIENTATION_PROCESS (\d+)$', data)
    identity = unique(rb'^Name:\s*provider\nState:\s*([RS])[^\n]*\nTgid:\s*(\d+)\nPid:\s*(\d+)\nPPid:[^\n]*\nTracerPid:\s*0\nUid:\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\n', data)
    if identity[1:3] != (pid, pid) or identity[3:] != (b'29999',) * 4:
        raise ValueError('orientation process identity mismatch')
    for path, expected in {**REGISTRY, '/tmp/n00-qemu-orientation/provider': md5, f'/proc/{pid.decode()}/exe': md5}.items():
        if unique(rb'^([0-9a-f]{32})  ' + re.escape(path.encode()) + rb'$', data).decode() != expected:
            raise ValueError('orientation executable or original registry changed')
    return {'edge': edge, 'flat': False, 'pid': int(pid), 'uid': 29999,
            'original_registry_unchanged': True, 'registry': '/tmp/n00-qemu-orientation/providers'}


def command(serial, wait_line, operation, edge, tag, inspect=False, delay=0):
    if operation not in ('start', 'set', 'inspect') or edge not in EDGES.values() or not re.fullmatch('[a-z]+', tag):
        raise ValueError('invalid orientation command')
    inspect_cmd = ' && sh /tmp/n00-shell-guest.sh orientation-inspect' if inspect else ''
    serial.sendall((f"printf '\nN00_POSE_BEGIN_{tag}\n'; sh /tmp/n00-orientation-guest.sh {operation} {edge}"
                    f" && sleep {int(delay)}{inspect_cmd}; status=$?; "
                    f"printf '\nN00_POSE_EXIT_{tag}_%s\n' \"$status\"; printf '\nN00_POSE_DONE_{tag}\n'\n").encode())
    wait_line(f'N00_POSE_DONE_{tag}'.encode())


def run_probe(qmp, serial, wait_line, capture, display, rotation):
    if rotation != 270:
        raise ValueError('Calendar probe coordinates require rotation 270')

    def pointer(x, y, down):
        qmp.call('input-send-event', {'events': [
            {'type': 'abs', 'data': {'axis': 'x', 'value': round(x * 32767 / 479)}},
            {'type': 'abs', 'data': {'axis': 'y', 'value': round(y * 32767 / 863)}},
            {'type': 'btn', 'data': {'button': 'left', 'down': down}}]})

    pointer(295, 245, True)
    time.sleep(0.15)
    pointer(295, 245, False)
    for tag, edge, delay in (('portrait', 'left', 20), ('landscape', 'top', 8), ('restored', 'left', 8)):
        command(serial, wait_line, 'set', edge, tag, inspect=True, delay=delay)
        capture(f'orientation-{tag}')
        print(f'DIAGNOSTIC: Calendar {tag}', flush=True)
    # The observed original first-run page offers "No thanks" at this point.
    # This is a real touch, in this disposable guest, not a settings-file edit.
    pointer(240, 760, True)
    time.sleep(0.15)
    pointer(240, 760, False)
    for tag, edge in (('calendar', 'left'), ('calendarlandscape', 'top'), ('calendarrestored', 'left')):
        command(serial, wait_line, 'set', edge, tag, inspect=True, delay=8)
        capture(f'orientation-{tag}')
        print(f'DIAGNOSTIC: Calendar {tag}', flush=True)
    pointer(0, 420, True)
    for index in range(1, 21):
        time.sleep(0.05)
        pointer(index * 21, 420, True)
    pointer(420, 420, False)
    command(serial, wait_line, 'inspect', 'left', 'home', inspect=True, delay=8)
    capture('orientation-home')


def validate_serial(data, home, md5):
    app = provider_pid = None
    observations = {}
    normalized = data.replace(b'\r', b'')
    # Validate markers before locating them so absent records fail uniformly.
    records = {tag: block(data, tag) for tag in STAGES}
    positions = [normalized.index(f'N00_POSE_BEGIN_{tag}\n'.encode()) for tag in STAGES]
    if positions != sorted(positions):
        raise ValueError('orientation observations out of order')
    for tag in STAGES:
        record = records[tag]
        edge = 'top' if tag.endswith('landscape') else 'left'
        provider = validate_provider(record, edge, md5)
        if provider_pid is not None and provider_pid != provider['pid']:
            raise ValueError('orientation provider restarted during rotation')
        provider_pid = provider['pid']
        pid = unique(rb'^N00_CALENDAR_PROCESS (\d+)$', record)
        identity = unique(rb'^Name:\s*organiser\nState:\s*([RS])[^\n]*\nTgid:\s*(\d+)\nPid:\s*(\d+)\nPPid:[^\n]*\nTracerPid:\s*0\nUid:\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\n', record)
        if identity[1:3] != (pid, pid) or identity[3:] != (b'29999',) * 4:
            raise ValueError('Calendar process identity mismatch')
        for path in ('/usr/bin/organiser', f'/proc/{pid.decode()}/exe'):
            if unique(rb'^([0-9a-f]{32})  ' + re.escape(path.encode()) + rb'$', record).decode() != CALENDAR_MD5:
                raise ValueError('not the original Calendar executable')
        if record.splitlines().count(b'CONTEXT_PROVIDERS=/tmp/n00-qemu-orientation/providers') != 1:
            raise ValueError('Calendar did not inherit the private ContextKit registry')
        window = unique(rb'^N00_X11_WINDOW id=([0-9a-f]{8}) map=2 geometry=864x480\+0\+0 pid=' + pid +
                        rb' class=' + b'organiser\0Organiser\0'.hex().encode() + rb'$', record)
        if app is not None and app != (pid, window):
            raise ValueError('Calendar restarted or replaced its window during rotation')
        app = pid, window
        angle = unique(rb'^N00_X11_ORIENTATION id=' + window + rb' angle=(\d+)$', record)
        if int(angle) != (0 if edge == 'top' else 270):
            raise ValueError('Calendar did not follow the virtual pose')
        clients = unique(rb'^N00_X11_CLIENTS ([0-9a-f,]+)$', record).split(b',')
        active = unique(rb'^N00_X11_ACTIVE id=([0-9a-f]{8})$', record)
        expected = home['home_window'].encode() if tag == 'home' else window
        if window not in clients or home['home_window'].encode() not in clients or active != expected or clients[-1] != expected:
            raise ValueError('wrong foreground window in Calendar regression')
        home_line = (f"N00_X11_WINDOW id={home['home_window']} map=2 geometry=864x480+0+0 pid={home['pids']['meegotouchhome']} class=".encode()
                     + b'meegotouchhome\0Meegotouchhome\0'.hex().encode())
        for line in (home_line, f"N00_X11_WM check={home['wm_window']} self={home['wm_window']}".encode(),
                     f"N00_X11_COMPOSITOR owner={home['wm_window']}".encode(), b'N00_X11_INSPECT_OK'):
            if record.splitlines().count(line) != 1:
                raise ValueError('Home/compositor identity changed')
        observations[tag] = {'angle': int(angle), 'edge': edge, 'active': active.decode()}
    return {'pid': int(app[0]), 'window': app[1].decode(), 'runtime_md5': CALENDAR_MD5,
            'provider_pid': provider_pid, 'same_instance': True, 'observations': observations}


def describe_frames(initial, frames):
    """Full-frame evidence even when exact restoration fails; no masked regions."""
    header = b'P6\n864 480\n255\n'
    if set(frames) != set(STAGES):
        raise ValueError('missing or unexpected Calendar framebuffer stage')
    for frame in (initial, *frames.values()):
        if not frame.startswith(header) or len(frame) != len(header) + 864 * 480 * 3:
            raise ValueError('invalid Calendar framebuffer')

    def difference(first, second):
        if first == second:
            return {'exact': True, 'changed_pixels': 0, 'bbox': None}
        count = 0
        left, top, right, bottom = 864, 480, 0, 0
        a, b = first[len(header):], second[len(header):]
        for i in range(0, len(a), 3):
            if a[i:i + 3] != b[i:i + 3]:
                y, x = divmod(i // 3, 864)
                count += 1
                left, top = min(left, x), min(top, y)
                right, bottom = max(right, x + 1), max(bottom, y + 1)
        return {'exact': False, 'changed_pixels': count, 'bbox': [left, top, right, bottom]}

    return {
        'native_size': [864, 480],
        'bbox_coordinates': 'native framebuffer [left, top, right, bottom], exclusive right/bottom; not rotated display',
        'round_trips': {
            'portrait': difference(frames['portrait'], frames['restored']),
            'calendar': difference(frames['calendar'], frames['calendarrestored']),
            'home': difference(initial, frames['home']),
        },
        'rotation_changed_pixels': {
            'portrait': difference(frames['portrait'], frames['landscape'])['changed_pixels'],
            'calendar': difference(frames['calendar'], frames['calendarlandscape'])['changed_pixels'],
        },
        'initial_native_rgb_sha256': hashlib.sha256(initial[len(header):]).hexdigest(),
        'native_rgb_sha256': {tag: hashlib.sha256(frames[tag][len(header):]).hexdigest() for tag in STAGES},
    }


def validate_frames(initial, frames):
    details = describe_frames(initial, frames)
    if not details['round_trips']['home']['exact']:
        raise ValueError('Calendar edge return did not restore Home pixels exactly')
    for start in ('portrait', 'calendar'):
        if not details['round_trips'][start]['exact']:
            raise ValueError(f'{start} pixels were not restored after rotation')
        if details['rotation_changed_pixels'][start] < 20000 or frames[start] == initial:
            raise ValueError('Calendar did not visibly rotate')
    if frames['calendar'] == frames['portrait']:
        raise ValueError('Calendar remained on the initial onboarding screen')
    return {'rotation_changed_pixels': details['rotation_changed_pixels'],
            'portrait_restored_exactly': True, 'home_restored_exactly': True,
            'native_rgb_sha256': details['native_rgb_sha256']}


def validate_probe(data, home, md5, initial, frames):
    return {**validate_serial(data, home, md5), **validate_frames(initial, frames)}
