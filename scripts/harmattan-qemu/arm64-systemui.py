"""Verify the original System UI provider; never accept a GPU warning as clean."""
import re

SYSUID_MD5 = '6e6ca0153aea0bf3b4556c08d68f934f'


def enabled(mode, interactive):
    if mode not in (None, 'on', 'off'):
        raise ValueError('invalid System UI mode')
    return interactive if mode is None else mode == 'on'


def unique(pattern, data):
    found = re.findall(pattern, data, re.M)
    if len(found) != 1:
        raise ValueError('missing or ambiguous original System UI evidence')
    return found[0]


def validate_serial(data, minimum_reports=3):
    data = data.replace(b'\r', b'')
    lines = data.splitlines()
    records = re.findall(rb'(?:^|\n)N00_SYSTEMUI_REPORT_BEGIN\n(.*?)\nN00_SYSTEMUI_REPORT_END\n', data, re.S)
    if (len(records) < minimum_reports or lines.count(b'N00_SYSTEMUI_REPORT_BEGIN') != len(records)
            or lines.count(b'N00_SYSTEMUI_REPORT_END') != len(records)):
        raise ValueError('System UI reports are missing or incomplete')
    identity = None
    for record in records:
        pid = unique(rb'^N00_SYSTEMUI_PROCESS (\d+)$', record)
        proc = unique(rb'^Name:\s*sysuid\nState:\s*([RS])[^\n]*\nTgid:\s*(\d+)\nPid:\s*(\d+)\nPPid:[^\n]*\nTracerPid:\s*0\nUid:\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\n', record)
        if proc[1:3] != (pid, pid) or proc[3:] != (b'29999',) * 4:
            raise ValueError('System UI process identity mismatch')
        for path in (b'/usr/bin/sysuid', b'/proc/' + pid + b'/exe'):
            if unique(rb'^([0-9a-f]{32})  ' + re.escape(path) + rb'$', record).decode() != SYSUID_MD5:
                raise ValueError('System UI executable was replaced')
        values = {}
        for tag in ('OWNER', 'PIXMAP'):
            matches = re.findall(rb'(?:^|\n)N00_SYSTEMUI_' + tag.encode() + rb'_BEGIN\n(.*?)\nN00_SYSTEMUI_' + tag.encode() + rb'_END', record, re.S)
            if len(matches) != 1:
                raise ValueError('missing System UI D-Bus reply')
            values[tag] = int(unique(rb'^\s*uint32 (\d+)$', matches[0]))
        if values['OWNER'] != int(pid) or values['PIXMAP'] == 0:
            raise ValueError('shared pixmap is absent or service owner is not original sysuid')
        current = (int(pid), values['PIXMAP'])
        if identity is not None and identity != current:
            raise ValueError('System UI restarted or replaced its shared pixmap')
        identity = current
    pixmaps = re.findall(rb'^N00_X11_STATUSBAR window=([0-9a-f]{8}) pixmap=([0-9a-f]{8}) size=(\d+)x(\d+) depth=(\d+)$', data, re.M)
    # Startup itself runs before the compositor. Home/settled provide the first
    # independent X11 geometry observations; later app probes repeat them.
    if minimum_reports >= 3 and (len(pixmaps) < len(records) - 1 or b'N00_X11_STATUSBAR absent' in lines):
        raise ValueError('no real statusbar X11 pixmap geometry')
    if pixmaps:
        first = pixmaps[0]
        if any(value != first for value in pixmaps) or int(first[0], 16) == 0 or int(first[1], 16) != identity[1]:
            raise ValueError('D-Bus and X11 statusbar identities disagree')
        width, height, depth = map(int, first[2:])
        if not (0 < width <= 4096 and 0 < height <= 4096 and depth in (16, 24, 32)):
            raise ValueError('invalid statusbar pixmap dimensions')
    else:
        width = height = depth = None
    return {'pid': identity[0], 'uid': 29999, 'runtime_md5': SYSUID_MD5,
            'pixmap': f'{identity[1]:08x}', 'size': [width, height], 'depth': depth,
            'reports': len(records), 'same_instance': True,
            'scope': 'original statusbar provider only; unavailable device services are not simulated'}


def validate_host(data, live=False):
    """Explicit three-client profile; the historical two-client gate is intact.

    Original guest EGL double-terminate is already independently demonstrated
    by the public API probe. Preserve the release/NULL rejection pair as a
    known guest API defect, not an OpenGL warning and never an arbitrary error.
    """
    lines = data.strip().split(b'\n')
    connected, current, disconnected, terminations = set(), set(), [], []
    render = summary = None
    index = 0
    while index < len(lines):
        line = lines[index]
        match = re.fullmatch(rb'N00_GLES connect client=([0-3]) abi=([12])', line)
        if match:
            client, abi = map(int, match.groups())
            if client in connected or abi != (1 if client == 0 else 2) or client != len(connected) or disconnected:
                raise ValueError('invalid System UI GPU client creation')
            connected.add(client)
        elif match := re.fullmatch(rb'N00_GLES current client=([1-3]) es=2 renderer=Apple [^\n]+', line):
            client = int(match[1])
            if client not in connected or client in current or disconnected:
                raise ValueError('missing/duplicate System UI GPU context')
            current.add(client)
        elif match := re.fullmatch(rb'N00_GLES terminate client=([1-3]) released=1 backend=retained', line):
            client = int(match[1])
            if terminations or client not in current or disconnected or index + 1 >= len(lines):
                raise ValueError('unexpected guest EGL lifecycle')
            expected = f'N00_GLES terminate client={client} rejected=bad-display'.encode()
            if lines[index + 1] != expected:
                raise ValueError('guest EGL NULL-display rejection was changed or missing')
            terminations.append(client)
            index += 1
        elif match := re.fullmatch(rb'N00_GLES disconnect client=([0-3])', line):
            client = int(match[1])
            if live or current != {1, 2, 3} or len(disconnected) >= 4 or client != (1, 2, 3, 0)[len(disconnected)] or render:
                raise ValueError('invalid System UI worker teardown')
            disconnected.append(client)
        elif match := re.fullmatch(rb'N00_GLES render compiles=(\d+) links=(\d+) uploads=(\d+) draws=(\d+) rejects=0', line):
            if live or render or disconnected != [1, 2, 3, 0] or not all(int(n) > 0 for n in match.groups()):
                raise ValueError('invalid System UI render summary')
            render = tuple(map(int, match.groups()))
        elif match := re.fullmatch(rb'N00_GLES summary calls=(\d+) swaps=(\d+) faults=0 workers=joined', line):
            if live or summary or not render or index != len(lines) - 1 or not all(int(n) > 0 for n in match.groups()):
                raise ValueError('invalid System UI final summary')
            summary = tuple(map(int, match.groups()))
        else:
            raise ValueError('unexpected System UI GPU log: ' + line.decode(errors='replace'))
        index += 1
    if connected != {0, 1, 2, 3} or current != {1, 2, 3} or (not live and (not render or not summary)):
        raise ValueError('incomplete System UI GPU lifecycle')
    result = {'clean': True, 'warnings': [], 'gpu_contexts': 3,
              'known_guest_api_defects': [f'client {c}: original eglTerminate repeats with NULL, correctly rejected' for c in terminations]}
    if live:
        result['shutdown_summary_pending'] = True
    else:
        result.update(zip(('compiles', 'links', 'uploads', 'draws', 'calls', 'swaps'), (*render, *summary)))
        result.update(rejects=0, faults=0, workers_joined=True)
    return result
