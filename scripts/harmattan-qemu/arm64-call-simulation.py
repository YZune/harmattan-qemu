"""Original call-ui on an isolated bus, with explicitly synthetic call state."""
import array
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import time

UI_MD5 = 'c9d625ced99916c45464069ccedf6c03'
GCONF_MD5 = '3103cb2bab05954ee11de77cb2b1096c'
GUEST = '/tmp/n00-ui-helpers/call-simulation-guest.sh'


def validate_configuration(mode, *, interactive, ready, profile, rotation, test):
    if mode not in ('off', 'on'):
        raise ValueError('Call simulation must be off or on')
    if test and mode != 'on':
        raise ValueError('Call diagnostic requires explicit call simulation')
    if mode == 'on' and (not interactive or not ready or profile or rotation != 270):
        raise ValueError('Call simulation requires upright interactive readiness and a disposable disk')


def prepare(*, locked=False):
    scripts = Path(__file__).resolve().parent
    root = scripts.parents[1]
    work = Path(os.environ.get('HARMATTAN_PORT_WORKSPACE', root / 'extracted/qemu-arm64-port'))
    subprocess.run(['sh', str(scripts / 'build-call-simulation-guest.sh')], check=True)
    binary = (work / 'call-simulation-guest/n00-call-simulation').read_bytes()
    if not binary.startswith(b'\x7fELF\x01\x01') or binary[18:20] != b'\x28\x00':
        raise ValueError('Expected an ARM32 little-endian call simulation helper')
    payloads = {'n00-call-simulation': binary,
            'call-simulation-guest.sh': (scripts / 'call-simulation-guest.sh').read_bytes()}
    info = {
        'enabled': True, 'synthetic_calls': True, 'real_telephony': False,
        'helper_md5': hashlib.md5(binary).hexdigest(),
        'helper_sha256': hashlib.sha256(binary).hexdigest(),
        'original_ui_md5': UI_MD5, 'scope': 'isolated original call-ui presentation; no modem, SIM or microphone'}
    info['locked'] = locked
    if locked:
        for name in ('n00-call-lockscreen', 'n00-call-livepixmap.so'):
            data = (work / 'call-simulation-guest' / name).read_bytes()
            if not data.startswith(b'\x7fELF\x01\x01') or data[18:20] != b'\x28\x00':
                raise ValueError('Expected ARM32 lock-call helper')
            payloads[name] = data
        payloads['call-lockscreen-guest.sh'] = (scripts / 'call-lockscreen-guest.sh').read_bytes()
        info['relay_md5'] = hashlib.md5(payloads['n00-call-lockscreen']).hexdigest()
        info['pixmap_sha256'] = hashlib.sha256(payloads['n00-call-livepixmap.so']).hexdigest()
    return payloads, info



def validate_host(data, systemui_validator):
    """One additional original call-ui context, closed before the desktop.

    Validate its exact lifetime, then apply the unchanged three-context gate
    to every other line, including render counters, errors and final teardown.
    """
    lines = data.strip().splitlines()
    expected = (b'N00_GLES connect client=4 abi=2',
                rb'N00_GLES current client=4 es=2 renderer=Apple [^\n]+',
                b'N00_GLES disconnect client=4')
    positions = []
    for pattern in expected:
        matches = [i for i, line in enumerate(lines) if re.fullmatch(pattern, line)]
        if len(matches) != 1:
            raise ValueError('Missing/duplicate call-ui GPU lifecycle')
        positions.append(matches[0])
    connect, current, disconnect = positions
    desktop_current = [i for i, line in enumerate(lines)
                       if re.fullmatch(rb'N00_GLES current client=[1-3] es=2 renderer=Apple [^\n]+', line)]
    if (len(desktop_current) != 3 or not max(desktop_current) < connect < current < disconnect or
            lines[disconnect + 1:disconnect + 5] !=
            [f'N00_GLES disconnect client={c}'.encode() for c in (1, 2, 3, 0)]):
        raise ValueError('Invalid call-ui GPU lifetime relative to desktop')
    desktop = b'\n'.join(line for i, line in enumerate(lines) if i not in positions) + b'\n'
    result = systemui_validator(desktop)
    result.update(gpu_contexts=4, call_ui_context=True,
                  scope='original desktop plus one original call-ui; strict separate lifecycle')
    return result


def validate_report(data, info):
    def pid(label, digest):
        values = re.findall(rb'^N00_CALL_' + label + rb'_PID ([1-9][0-9]*)$', data, re.M)
        if len(values) != 1:
            raise ValueError('Missing unique call simulation process')
        value = int(values[0])
        actual = re.findall(rb'^([0-9a-f]{32})  /proc/' + values[0] + rb'/exe$', data, re.M)
        if actual != [digest.encode()]:
            raise ValueError('Call simulation executable identity mismatch')
        return value
    if info.get('locked'):
        relay = pid(b'RELAY', info['relay_md5'])
        if info.get('relay_pid', relay) != relay:
            raise ValueError('Lock call relay was replaced')
        info['relay_pid'] = relay
        if b'LOCK_FATAL' in data or b'LOCK_FORWARD_ERROR' in data or b'LIVE_FATAL' in data:
            raise ValueError('Original locked call bridge failed')
    backend = pid(b'BACKEND', info['helper_md5'])
    ui = pid(b'UI', UI_MD5)
    gconf = pid(b'GCONF', GCONF_MD5)
    if info.get('gconf_pid', gconf) != gconf:
        raise ValueError('Call configuration service was replaced')
    if info.get('backend_pid', backend) != backend or info.get('ui_pid', ui) != ui:
        raise ValueError('Call simulation process was replaced')
    blocks = re.findall(rb'^N00_CALL_STATUS_BEGIN\n(.*?)^N00_CALL_STATUS_END$', data, re.M | re.S)
    numbers = re.findall(rb'^\s+uint32 (\d+)$', blocks[0], re.M) if len(blocks) == 1 else []
    if len(numbers) != 3 or int(numbers[0]) not in range(4) or int(numbers[2]) not in (0, 1):
        raise ValueError('Malformed call simulation state')
    if any(marker in data for marker in (b'DEMO_FATAL', b'DEMO_TONE_ERROR', b'DEMO_REMOTE_ERROR')):
        raise ValueError('Call simulation backend reported a failure')
    info.update(backend_pid=backend, ui_pid=ui, gconf_pid=gconf)
    info['ringtone_requests'] = [int(value) for value in re.findall(rb'^DEMO_TONE_REQUEST sequence=(\d+)$', data, re.M)]
    return {'state': int(numbers[0]), 'sequence': int(numbers[1]), 'ringing_audio': bool(int(numbers[2]))}


def phase(serial, wait_line, output, action, tag, info, audio=None):
    if action not in ('setup', 'incoming', 'end', 'report', 'stop', 'invalid-input', 'busy', 'stale', 'lock-negative') or not re.fullmatch('[a-z][a-z0-9-]*', tag):
        raise ValueError('Invalid call simulation phase')
    marker = 'N00_CALL_PHASE_' + tag.replace('-', '_')
    environment = ''
    if action == 'setup':
        environment = 'N00_CALL_AUDIO=off '
        if audio:
            if not re.fullmatch(r'tcp:10\.0\.2\.2:[1-9][0-9]{0,4}', audio.guest_server):
                raise ValueError('Invalid private call audio address')
            environment = 'N00_CALL_AUDIO=pulse ' + audio.guest_environment() + ' '
    if action == 'setup' and info.get('locked'):
        environment += 'N00_CALL_LOCKSCREEN=on '
    command = f"printf '\\n{marker}_BEGIN\\n'; {environment}sh {GUEST} {action}; "
    command += f"printf '\\n{marker}_EXIT_%s\\n{marker}_DONE\\n' $?\n"
    serial.sendall(command.encode())
    wait_line((marker + '_DONE').encode())
    data = (output / 'serial.log').read_bytes().replace(b'\r', b'')
    blocks = re.findall(rb'^' + marker.encode() + rb'_BEGIN\n(.*?)^' + marker.encode() +
                        rb'_EXIT_(\d+)\n' + marker.encode() + rb'_DONE$', data, re.M | re.S)
    if len(blocks) != 1 or blocks[0][1] != b'0':
        raise ValueError(f'Call simulation {tag} failed; inspect guest serial log')
    body = blocks[0][0]
    if action in ('setup', 'report'):
        state = validate_report(body, info)
        info.setdefault('observations', {})[tag] = state
    else:
        state = None
    if action == 'stop':
        if body.splitlines().count(b'N00_CALL_STOPPED') != 1:
            raise ValueError('Missing call simulation shutdown')
        info['stopped'] = True
    (output / 'call-simulation-result.json').write_text(json.dumps(info, indent=2) + '\n')
    return state


def validate_ringtone(data):
    if len(data) % 4 or len(data) < 44100 * 4 * 5:
        raise ValueError('Insufficient stereo ringtone PCM')
    samples = array.array('h', data)
    if __import__('sys').byteorder != 'little':
        samples.byteswap()
    rms = math.sqrt(sum(value * value for value in samples) / len(samples))
    tail = samples[-44100 * 2 * 4:]
    tail_rms = math.sqrt(sum(value * value for value in tail) / len(tail))
    if rms <= 20 or tail_rms <= 20:
        raise ValueError('Ringtone output was silent or stopped before the sample ended')
    return {'seconds': round(len(data) / 176400, 3), 'rms': round(rms, 2),
            'tail_rms': round(tail_rms, 2), 'sha256': hashlib.sha256(data).hexdigest(),
            'scope': 'private CoreAudio output monitor; no acoustic or microphone recording'}


def validate_pixels(ppm, stage):
    """Reject original MTheme missing-image markers and absent main controls.

    Capture is the upright 480x864 screen. Check original resource colours and
    white glyphs, not fabricated replacement artwork or byte-identical frames.
    """
    header = b'P6\n480 864\n255\n'
    if not ppm.startswith(header) or len(ppm) != len(header) + 480 * 864 * 3:
        raise ValueError('Call presentation requires a complete upright RGB frame')
    pixels = ppm[len(header):]
    def region(box):
        left, top, right, bottom = box
        return [tuple(pixels[(y * 480 + x) * 3:(y * 480 + x) * 3 + 3])
                for y in range(top, bottom) for x in range(left, right)]
    # MThemePrivate::invalidPixmap uses (255,64,64); framebuffer quantization
    # can reduce green/blue to 60. Real red button artwork contains gradients.
    markers = sum(1 for r, g, b in region((0, 36, 480, 864))
                  if r >= 248 and 56 <= g <= 68 and 56 <= b <= 68)
    if markers > 500:
        raise ValueError('Original call-ui contains missing theme resource markers')
    boxes = {'incoming': [(18, 425, 228, 489), (252, 425, 462, 489)],
             'answered': [(20, 742, 460, 808)]}
    if stage not in boxes:
        raise ValueError('Unknown call presentation stage')
    avatar = region((16, 318, 80, 382))
    if sum(1 for r, g, b in avatar if min(r, g, b) > 200) < 100:
        raise ValueError('Original caller avatar glyph is missing')
    counts = []
    for index, box in enumerate(boxes[stage]):
        values = region(box)
        green = stage == 'incoming' and index == 0
        if green:
            colour = sum(1 for r, g, b in values if g > 70 and g > r * 1.3 and g > b * 1.3)
        else:
            colour = sum(1 for r, g, b in values if r > 80 and r > g * 1.3 and r > b * 1.3)
        glyph = sum(1 for r, g, b in values if min(r, g, b) > 200)
        if colour < 1500 or glyph < 60:
            raise ValueError('Original call button colour or glyph is missing')
        counts.append({'colour_pixels': colour, 'glyph_pixels': glyph})
    return {'missing_resource_pixels': markers, 'controls': counts,
            'scope': 'resource markers and main button pixels; separate visual review required'}


def run_probe(qmp, serial, wait_line, capture, drain, output, info, audio):
    def act(action, tag):
        return phase(serial, wait_line, output, action, tag, info)
    def check(tag, state, sequence, ringing=False):
        observed = act('report', tag)
        if observed != {'state': state, 'sequence': sequence, 'ringing_audio': ringing}:
            raise ValueError(f'Unexpected call state at {tag}: {observed}')
        if audio:
            streams = json.loads(audio.control('--format=json', 'list', 'sink-inputs'))
            if ringing:
                if len(streams) != 1 or streams[0]['corked'] or streams[0]['mute']:
                    raise ValueError('Expected one playing simulated ringtone stream')
                if streams[0]['properties'].get('application.process.binary') != 'n00-call-simulation':
                    raise ValueError('Unexpected ringtone producer')
            elif streams:
                raise ValueError('Audio stream survived simulated call stop/mute')
    def tap(x, y):
        for down in (True, False):
            qmp.call('input-send-event', {'events': [
                {'type': 'abs', 'data': {'axis': 'x', 'value': round(x * 32767 / 479)}},
                {'type': 'abs', 'data': {'axis': 'y', 'value': round(y * 32767 / 863)}},
                {'type': 'btn', 'data': {'button': 'left', 'down': down}}]})
            drain(.12)
        drain(2)
    def incoming_ready(sequence):
        for attempt in range(20):
            state = act('report', f'incoming-{sequence}-wait-{attempt}')
            if (state['state'] == 1 and state['sequence'] == sequence and
                    sequence in info['ringtone_requests'] and state['ringing_audio'] == bool(audio)):
                drain(2)
                return
            drain(1)
        raise ValueError('Original call-ui did not finish presenting the simulated incoming call')
    act('invalid-input', 'invalid-signature')
    check('still-idle', 0, 0)
    act('incoming', 'first-incoming')
    incoming_ready(1)
    capture('call-incoming')
    info.setdefault('pixels', {})['incoming'] = validate_pixels((output / 'call-incoming.ppm').read_bytes(), 'incoming')
    check('ringing', 1, 1, bool(audio))
    act('busy', 'reject-overlap')
    check('same-incoming', 1, 1, bool(audio))
    if audio:
        pcm = output / 'call-ringtone.pcm'
        with pcm.open('xb') as stream, (output / 'call-ringtone-monitor.log').open('xb') as log:
            process = subprocess.Popen([str(audio.parec), '--device=' + audio.monitor, '--format=s16le',
                '--rate=44100', '--channels=2', '--raw'], env=audio.env, stdout=stream, stderr=log)
            try:
                drain(32)
                if process.poll() is not None:
                    raise ValueError('Ringtone monitor stopped early')
            finally:
                process.terminate()
                process.wait(timeout=5)
        info['ringtone_pcm'] = validate_ringtone(pcm.read_bytes())
    tap(240, 685)
    capture('call-ringtone-muted')
    check('ringtone-muted', 1, 1)
    tap(124, 457)
    drain(3)
    capture('call-answered')
    info['pixels']['answered'] = validate_pixels((output / 'call-answered.ppm').read_bytes(), 'answered')
    check('answered', 2, 1)
    tap(240, 774)
    drain(3)
    capture('call-hung-up')
    check('hung-up', 3, 1)
    act('incoming', 'second-incoming')
    incoming_ready(2)
    check('second-ringing', 1, 2, bool(audio))
    act('stale', 'reject-stale-channel')
    check('second-still-ringing', 1, 2, bool(audio))
    tap(360, 457)
    capture('call-rejected')
    check('rejected', 3, 2)
    act('incoming', 'third-incoming')
    incoming_ready(3)
    check('third-ringing', 1, 3, bool(audio))
    act('end', 'remote-cancel')
    drain(3)
    capture('call-remote-cancelled')
    check('remote-cancelled', 3, 3)
    # Distinct images supplement protocol/button evidence; visual inspection is separate.
    images = [(output / (name + '.png')).read_bytes() for name in
              ('call-incoming', 'call-answered', 'call-hung-up')]
    if len({hashlib.sha256(value).hexdigest() for value in images}) != 3:
        raise ValueError('Call presentation did not change across its main states')
    info['diagnostic'] = {'protocol_audio_pixels_passed': True, 'input': 'headless QMP taps',
        'scenarios': ['incoming', 'ringtone-mute', 'answer', 'hangup', 'reject', 'remote-cancel', 'repeat'],
        'physical_input': False, 'real_voice': False}
    (output / 'call-simulation-result.json').write_text(json.dumps(info, indent=2) + '\n')


def validate_locked_pixels(ppm):
    header = b'P6\n480 864\n255\n'
    if not ppm.startswith(header) or len(ppm) != len(header) + 480 * 864 * 3:
        raise ValueError('Expected complete upright lock-call frame')
    pixels = ppm[len(header):]
    green_rows = []
    for y in range(550, 864):
        green = 0
        for x in range(16, 464):
            r, g, b = pixels[(y * 480 + x) * 3:(y * 480 + x) * 3 + 3]
            green += g > 90 and g > r * 1.3 and g > b * 1.3
        if green > 350:
            green_rows.append(y)
    top = min(green_rows) if green_rows else 864
    text = sum(min(pixels[(y * 480 + x) * 3:(y * 480 + x) * 3 + 3]) > 220
               for y in range(max(550, top - 190), max(550, top - 5)) for x in range(16, 464))
    if len(green_rows) < 25 or text < 500:
        raise ValueError('Native green lock event or original caller text is absent')
    return {'green_top': min(green_rows), 'green_rows': len(green_rows), 'caller_text_pixels': text}


def run_locked_probe(control, qmp, serial, wait_line, capture, drain, output, info, audio):
    """Original lock event, short/full swipes and call state are separate gates."""
    def act(action, tag):
        return phase(serial, wait_line, output, action, tag, info)
    def check(tag, state, sequence):
        observed = act('report', tag)
        if observed['state'] != state or observed['sequence'] != sequence:
            raise ValueError(f'Unexpected locked call state at {tag}: {observed}')
    def lock(mapped, low=None):
        value = control.phase(serial, wait_line, 'inspect')
        if value['mapped'] != mapped or (low is not None and value['low_power'] != low):
            raise ValueError(f'Unexpected locked call window state: {value}')
    def pointer(x, y, down):
        qmp.call('input-send-event', {'events': [
            {'type': 'abs', 'data': {'axis': 'x', 'value': round(x * 32767 / 479)}},
            {'type': 'abs', 'data': {'axis': 'y', 'value': round(y * 32767 / 863)}},
            {'type': 'btn', 'data': {'button': 'left', 'down': down}}]})
    def tap(x, y):
        pointer(x, y, True); drain(.12); pointer(x, y, False); drain(3)
    def swipe(end):
        pointer(240, 800, True)
        for step in range(1, 21):
            drain(.04); pointer(240, 800 + (end - 800) * step / 20, True)
        pointer(240, end, False); drain(3)
    def incoming(sequence):
        act('incoming', f'locked-incoming-{sequence}')
        for attempt in range(20):
            value = act('report', f'locked-wait-{sequence}-{attempt}')
            if value['state'] == 1 and sequence in info['ringtone_requests']:
                drain(3); lock(True, False); return
            drain(1)
        raise ValueError('Original locked incoming event was not ready')
    lock(False)
    control.phase(serial, wait_line, 'press'); lock(True, True)
    capture('locked-call-before')
    act('invalid-input', 'locked-invalid-signature')
    act('lock-negative', 'locked-reject-impersonation')
    incoming(1)
    capture('locked-call-banner')
    info['locked_banner'] = validate_locked_pixels((output / 'locked-call-banner.ppm').read_bytes())
    # Retain successive frames for review of original breathing movement.
    for frame in range(6):
        drain(.3); capture(f'locked-call-motion-{frame}')
        info.setdefault('locked_motion_frames', []).append(validate_locked_pixels((output / f'locked-call-motion-{frame}.ppm').read_bytes()))
    act('busy', 'locked-reject-overlap')
    tap(240, 795); lock(True, False); check('locked-tap-no-answer', 1, 1)
    swipe(775); lock(True, False); check('locked-short-swipe', 1, 1)
    swipe(250); lock(False); check('locked-open-still-incoming', 1, 1)
    capture('locked-call-expanded')
    info.setdefault('pixels', {})['locked-expanded'] = validate_pixels((output / 'locked-call-expanded.ppm').read_bytes(), 'incoming')
    tap(124, 457); check('locked-answered', 2, 1)
    capture('locked-call-answered')
    info['pixels']['locked-answered'] = validate_pixels((output / 'locked-call-answered.ppm').read_bytes(), 'answered')
    tap(240, 774); check('locked-hung-up', 3, 1); lock(True, True)
    capture('locked-call-restored')
    incoming(2)
    act('stale', 'locked-reject-stale-channel')
    swipe(250); lock(False); check('locked-second-expanded', 1, 2)
    tap(360, 457); check('locked-rejected', 3, 2); lock(True, True)
    incoming(3)
    act('end', 'locked-remote-cancel'); drain(3)
    check('locked-cancelled', 3, 3); lock(True, True)
    capture('locked-call-cancelled')
    # Also enter from the already awake wallpaper, preserving that mode.
    control.phase(serial, wait_line, 'press'); lock(True, False)
    incoming(4); act('end', 'locked-wallpaper-cancel'); drain(3)
    check('locked-wallpaper-ended', 3, 4); lock(True, False)
    info['diagnostic'] = {'protocol_pixels_passed': True, 'input': 'headless QMP taps/swipes',
        'scenarios': ['clock-incoming', 'native-lock-event', 'tap-no-answer', 'short-swipe-no-answer',
                     'swipe-opens-controls', 'answer', 'hangup-restores-clock', 'reject', 'remote-cancel',
                     'wallpaper-incoming', 'overlap-rejected', 'stale-channel-rejected'],
        'physical_input': False, 'real_voice': False, 'animation_timing_measured': False}
    (output / 'call-simulation-result.json').write_text(json.dumps(info, indent=2) + '\n')
