"""Original Calculator functional probe; host warnings remain a separate gate."""
import hashlib
import importlib.util
from pathlib import Path
import re
import time

CLOCK_SPEC = importlib.util.spec_from_file_location('guest_clock', Path(__file__).with_name('arm64-clock.py'))
guest_clock = importlib.util.module_from_spec(CLOCK_SPEC)
CLOCK_SPEC.loader.exec_module(guest_clock)

CALC_MD5 = 'b59070fbc46bf164750a2d3f4960d068'
# Full native-coordinate RGB frames, visually checked against the actual
# original Calculator after a Home tap and the real 2 + 3 = key sequence.
ZERO_RGB = '7cf630898970109a10df0f44f4764708ee284b8a320807620da2a2fc46833425'
FIVE_RGB = '430d0a56a69aa4c609e88749d5ade393a8b43428448efa7ac830634f4c0d14a8'
STAGES = ('before', 'opened', 'sum', 'returned', 'reopened', 'final')
TEXTURE_WARNING = (b'UNSUPPORTED (log once): POSSIBLE ISSUE: unit 0 GLD_TEXTURE_INDEX_2D is '
                   b'unloadable and bound to sampler type (Float) - using zero texture because texture unloadable')


def run_probe(qmp, serial, wait_line, capture, display, rotation):
    width, height = (480, 864) if rotation in (90, 270) else (864, 480)

    def pointer(px, py, down):
        # Input points use the observed upright 480x864 layout. Convert back
        # to the guest framebuffer, then into this run's QEMU surface.
        x, y = display.surface_point(py, 479 - px, rotation)
        qmp.call('input-send-event', {'events': [
            {'type': 'abs', 'data': {'axis': 'x', 'value': round(x * 32767 / (width - 1))}},
            {'type': 'abs', 'data': {'axis': 'y', 'value': round(y * 32767 / (height - 1))}},
            {'type': 'btn', 'data': {'button': 'left', 'down': down}},
        ]})

    def tap(x, y):
        pointer(x, y, True)
        time.sleep(0.15)
        pointer(x, y, False)
        time.sleep(0.4)

    def swipe_back():
        pointer(0, 420, True)
        for index in range(1, 21):
            time.sleep(0.05)
            pointer(index * 21, 420, True)
        pointer(420, 420, False)

    def observe(stage, delay):
        # Separate exact markers from echoed shell commands and record the
        # guest inspector exit status; a prompt alone is never a checkpoint.
        serial.sendall((f"sleep {delay}; printf '\\nN00_CALC_BEGIN_{stage}\\n'; "
                        f"sh /tmp/n00-shell-guest.sh calculator-inspect {stage}; status=$?; "
                        f"printf '\\nN00_CALC_EXIT_{stage}_%s\\n' \"$status\"; "
                        f"printf '\\nN00_CALC_DONE_{stage}\\n'\n").encode())
        wait_line(f'N00_CALC_DONE_{stage}'.encode())
        capture(f'calculator-{stage}')
        print(f'DIAGNOSTIC: Calculator observation {stage}', flush=True)

    observe('before', 0)
    tap(183, 692)
    observe('opened', 15)
    for point in ((240, 680), (380, 330), (380, 680), (380, 790)):
        tap(*point)
    observe('sum', 3)
    swipe_back()
    observe('returned', 8)
    tap(183, 692)
    observe('reopened', 8)
    swipe_back()
    observe('final', 8)


def observations(data):
    data = data.replace(b'\r', b'')
    lines = data.split(b'\n')[:-1]
    result = {}
    for stage in STAGES:
        begin = f'N00_CALC_BEGIN_{stage}'.encode()
        end = f'N00_CALC_DONE_{stage}'.encode()
        if lines.count(begin) != 1 or lines.count(end) != 1:
            raise ValueError('missing or duplicate Calculator observation')
        matches = re.findall(rb'(?:^|\n)' + begin + rb'\n(.*?)\n' + end + rb'\n', data, re.S)
        if len(matches) != 1:
            raise ValueError('invalid Calculator observation boundaries')
        block = matches[0]
        exits = re.findall(rb'^N00_CALC_EXIT_' + stage.encode() + rb'_(\d+)$', block, re.M)
        if exits != [b'0']:
            raise ValueError('Calculator inspector failed or did not finish')
        result[stage] = block
    positions = [lines.index(f'N00_CALC_BEGIN_{stage}'.encode()) for stage in STAGES]
    if positions != sorted(positions):
        raise ValueError('Calculator observations out of order')
    return result


def validate_serial(data, home):
    blocks = observations(data)
    app_pid = app_window = None
    for stage, block in blocks.items():
        def unique(pattern):
            records = re.findall(pattern, block, re.M)
            if len(records) != 1:
                raise ValueError('missing or ambiguous Calculator/X11 identity')
            return records[0]

        original = unique(rb'^([0-9a-f]{32})  /usr/bin/calc$')
        if original.decode() != CALC_MD5:
            raise ValueError('not the original PR1.3 Calculator executable')
        if block.split(b'\n').count(b'# HARMATTAN_QEMU_DIRECT_INVOKER') != 1:
            raise ValueError('QEMU-only direct launcher boundary not recorded')
        manager = unique(rb'^N00_X11_WM check=([0-9a-f]{8}) self=([0-9a-f]{8})$')
        owner = unique(rb'^N00_X11_COMPOSITOR owner=([0-9a-f]{8})$')
        if manager != (owner, owner) or owner.decode() != home['wm_window']:
            raise ValueError('compositor identity changed')
        clients = unique(rb'^N00_X11_CLIENTS ([0-9a-f,]+)$').split(b',')
        active = unique(rb'^N00_X11_ACTIVE id=([0-9a-f]{8})$')
        if block.split(b'\n').count(b'N00_X11_INSPECT_OK') != 1:
            raise ValueError('X11 inspection incomplete')
        home_identity = (f"N00_X11_WINDOW id={home['home_window']} map=2 geometry=864x480+0+0 "
                         f"pid={home['pids']['meegotouchhome']} class=".encode()
                         + b'meegotouchhome\0Meegotouchhome\0'.hex().encode())
        if block.split(b'\n').count(home_identity) != 1 or home['home_window'].encode() not in clients:
            raise ValueError('original Home identity changed or is no longer managed')
        if stage == 'before':
            if unique(rb'^N00_CALCULATOR_PROCESS ([^\n]+)$') != b'absent':
                raise ValueError('Calculator was already running before the Home tap')
            if active.decode() != home['home_window']:
                raise ValueError('Home was not active before tapping its icon')
            continue
        pid = unique(rb'^N00_CALCULATOR_PROCESS (\d+)$')
        identity = unique(rb'^Name:\s*calc\nState:\s*([RS])[^\n]*\nTgid:\s*(\d+)\nPid:\s*(\d+)'
                          rb'\nPPid:[^\n]*\nTracerPid:\s*0\nUid:\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\n')
        if identity[1:3] != (pid, pid) or identity[3:] != (b'29999',) * 4:
            raise ValueError('Calculator is stopped, traced or running as the wrong user')
        if unique(rb'^([0-9a-f]{32})  /proc/' + pid + rb'/exe$').decode() != CALC_MD5:
            raise ValueError('running Calculator executable identity mismatch')
        window = unique(rb'^N00_X11_WINDOW id=([0-9a-f]{8}) map=2 geometry=864x480\+0\+0 pid=' +
                        pid + rb' class=' + b'calc\0Calc\0'.hex().encode() + rb'$')
        if window not in clients:
            raise ValueError('Calculator is not managed')
        if app_pid is None:
            app_pid, app_window = pid, window
        elif (app_pid, app_window) != (pid, window):
            raise ValueError('Calculator restarted instead of resuming the same instance')
        expected_active = home['home_window'].encode() if stage in ('returned', 'final') else window
        if active != expected_active or clients[-1] != active:
            raise ValueError('wrong foreground window after Calculator input')
    return {'pid': int(app_pid), 'window': app_window.decode(), 'runtime_md5': CALC_MD5,
            'same_instance_resumed': True, 'home_returns': 2, 'observations': list(STAGES)}


def validate_frames(initial, frames, allow_statusbar_change=False, expect_statusbar_change=False):
    header = b'P6\n864 480\n255\n'
    def digest(data):
        if not data.startswith(header) or len(data) != len(header) + 864 * 480 * 3:
            raise ValueError('invalid normalized Calculator framebuffer')
        return hashlib.sha256(data[len(header):]).hexdigest()
    first = digest(initial)
    results = {stage: digest(frames[stage]) for stage in STAGES}
    statusbar_changes = {}
    for stage in ('before', 'returned', 'final'):
        if allow_statusbar_change:
            comparison = guest_clock.compare_home_frames(initial, frames[stage], True)
            if not comparison['content_equal']:
                raise ValueError('Home content outside the original statusbar was not restored exactly')
            statusbar_changes[stage] = comparison['statusbar_changed_pixels']
        elif frames[stage] != initial:
            raise ValueError('Home pixels were not restored exactly')
    if expect_statusbar_change and not any(statusbar_changes.get(stage, 0) for stage in ('returned', 'final')):
        raise ValueError('statusbar pixels did not advance across a verified minute change')
    if results['opened'] != ZERO_RGB:
        raise ValueError('Calculator initial zero frame differs from verified reference')
    if results['sum'] != FIVE_RGB or frames['reopened'] != frames['sum']:
        raise ValueError('2 + 3 = 5 frame or resumed result differs from verified reference')
    return {'native_rgb_sha256': results, 'initial_home_rgb_sha256': first,
            'reference_expression': '2 + 3 = 5',
            'home_content_matches': True,
            'statusbar_dynamic': allow_statusbar_change,
            'statusbar_region': 'left 72 pixels of native 864x480 Home' if allow_statusbar_change else None,
            'statusbar_changed_pixels': statusbar_changes,
            'full_frame_matches': not any(statusbar_changes.values())}


def inspect_host(data, desktop_validator):
    # Do not weaken the established desktop gate or report a warning as clean.
    # This exact observed warning can be classified for a PARTIAL diagnostic;
    # any other warning, unexpected lifecycle or rejected call still fails.
    lines = data.splitlines()
    count = lines.count(TEXTURE_WARNING)
    if count > 1:
        raise ValueError('repeated incomplete-texture warning')
    normal = b'\n'.join(line for line in lines if line != TEXTURE_WARNING) + b'\n'
    result = desktop_validator(normal)
    result.update(clean=not count, warnings=[TEXTURE_WARNING.decode()] if count else [])
    return result
