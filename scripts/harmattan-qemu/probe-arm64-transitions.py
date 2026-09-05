"""Sample real guest RAM during original Calculator transitions, not display FPS."""
import hashlib
import json
from pathlib import Path
import time

STAGES = ('open', 'return', 'restore', 'final')
BLACK = hashlib.sha256(bytes(864 * 480 * 3)).hexdigest()
HEADER = b'P6\n864 480\n255\n'


def rgb(ppm):
    if len(ppm) != len(HEADER) + 864 * 480 * 3 or not ppm.startswith(HEADER):
        raise ValueError('transition frame must be a complete native RGB PPM')
    return ppm[len(HEADER):]


def different_pixels(a, b):
    return sum(a[i:i + 3] != b[i:i + 3] for i in range(0, len(a), 3))


def summarize(samples, frames, home, zero, five):
    references = {'open': (home, zero), 'return': (five, home),
                  'restore': (home, five), 'final': (five, home)}
    if not samples or any(a['end'] >= b['end'] for a, b in zip(samples, samples[1:])):
        raise ValueError('missing or non-monotonic transition observations')
    order = []
    for sample in samples:
        if sample['stage'] in STAGES and (not order or order[-1] != sample['stage']):
            order.append(sample['stage'])
    if tuple(order) != STAGES:
        raise ValueError('missing, repeated or reordered transition stages')
    result = {}
    for stage in STAGES:
        observations = [s for s in samples if s['stage'] == stage]
        if len(observations) < 10:
            raise ValueError('incomplete transition observation')
        black = [s for s in observations if s['rgb_sha256'] == BLACK]
        intermediate = []
        for sample in observations:
            if 'frame' not in sample or sample['rgb_sha256'] == BLACK:
                continue
            pixels = rgb(frames[sample['frame']])
            if hashlib.sha256(pixels).hexdigest() != sample['rgb_sha256']:
                raise ValueError('transition image does not match sampled RAM digest')
            # Exclude pressed labels, static endpoints and fading scrollbars.
            # This is a bounded motion check, not semantic recognition or FPS.
            if all(different_pixels(pixels, ref) > 10000 for ref in references[stage]):
                intermediate.append(sample['frame'])
        result[stage] = {'samples': len(observations), 'black_samples': len(black),
                         'material_intermediate_frames': intermediate,
                         'motion_frames_present': len(intermediate) >= 3}
    return {'stages': result,
            'motion_frames_present': all(s['motion_frames_present'] for s in result.values()),
            'black_flash_eliminated_in_samples': all(not s['black_samples'] for s in result.values()),
            'scope': 'sampled guest RAM; may race guest writes; not display FPS, physical input latency or all-app acceptance'}


def run_probe(qmp, serial, wait_line, capture, display, rotation, out, drain, framebuffer):
    if rotation != 270:
        raise ValueError('transition touch coordinates require rotation 270')
    directory = out / 'transitions'
    ram = framebuffer.FrameProbe(qmp, directory, drain)
    records, inputs = [], []
    current, last = 'before', None
    started = time.monotonic()

    def read():
        nonlocal last
        record = ram.read()
        record.update(stage=current, relative=record['end'] - started)
        if record['rgb_sha256'] != last:
            pixels = framebuffer.framebuffer_rgb(ram.dump.read_bytes())
            name = f'{len(records):04d}.ppm'
            (directory / name).write_bytes(HEADER + pixels)
            record['frame'] = name
            last = record['rgb_sha256']
        records.append(record)

    def wait(seconds):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            read()
            drain(0.025)

    def pointer(x, y, down):
        inputs.append(dict(stage=current, relative=time.monotonic() - started, x=x, y=y, down=down))
        qmp.call('input-send-event', {'events': [
            {'type': 'abs', 'data': {'axis': 'x', 'value': round(x * 32767 / 479)}},
            {'type': 'abs', 'data': {'axis': 'y', 'value': round(y * 32767 / 863)}},
            {'type': 'btn', 'data': {'button': 'left', 'down': down}}]})

    def tap(x, y):
        pointer(x, y, True); wait(0.15); pointer(x, y, False)

    def swipe():
        pointer(0, 420, True)
        for i in range(1, 21):
            wait(0.05)
            pointer(i * 21, 420, True)
        pointer(420, 420, False)

    def observe(stage, delay):
        serial.sendall((f"sleep {delay}; printf '\\nN00_CALC_BEGIN_{stage}\\n'; "
                        f"sh /tmp/n00-shell-guest.sh calculator-inspect {stage}; status=$?; "
                        f"printf '\\nN00_CALC_EXIT_{stage}_%s\\n' \"$status\"; "
                        f"printf '\\nN00_CALC_DONE_{stage}\\n'\n").encode())
        wait_line(f'N00_CALC_DONE_{stage}'.encode())
        capture(f'calculator-{stage}')
        print(f'TRANSITION: {stage}', flush=True)

    try:
        observe('before', 0)
        current = 'open'
        # Cold launches in a background Cocoa window can start after 4 s.
        # Keep sampling through that interval instead of losing the entire
        # opening animation inside the later serial-only settling sleep.
        tap(183, 692); wait(12); observe('opened', 10)
        current = 'sum'
        for point in ((240, 680), (380, 330), (380, 680), (380, 790)):
            tap(*point); wait(0.4)
        observe('sum', 3)
        current = 'return'
        swipe(); wait(3); observe('returned', 5)
        current = 'restore'
        tap(183, 692); wait(3); observe('reopened', 5)
        current = 'final'
        swipe(); wait(3); observe('final', 5)
    finally:
        # Preserve incomplete evidence on errors; do not synthesize success.
        (out / 'transition-samples.json').write_text(json.dumps(dict(
            scope='guest RAM and input timestamps; no screendump or stop/cont during sampling',
            observer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            registers=ram.registers, samples=records, inputs=inputs), indent=2) + '\n')


def analyze(out, display, rotation):
    data = json.loads((out / 'transition-samples.json').read_text())
    frames = {s['frame']: (out / 'transitions' / s['frame']).read_bytes()
              for s in data['samples'] if 'frame' in s}
    reference = lambda name: rgb(display.native_ppm((out / (name + '.ppm')).read_bytes(), rotation))
    return summarize(data['samples'], frames, reference('settled'),
                     reference('calculator-opened'), reference('calculator-sum'))
