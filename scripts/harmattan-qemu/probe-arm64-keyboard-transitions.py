"""Observe Notes keyboard show/hide in guest RAM; never alter displayed frames."""
import hashlib
import json
from pathlib import Path
import time

STAGES = ('show', 'hide-save', 'show-again', 'hide-cancel')
HEADER = b'P6\n864 480\n255\n'
PIXELS = 864 * 480
BLACK = hashlib.sha256(bytes(PIXELS * 3)).hexdigest()


class Recorder:
    def __init__(self, qmp, out, drain, framebuffer):
        self.out, self.drain, self.framebuffer = out, drain, framebuffer
        self.directory = out/'keyboard-motion'
        self.ram = framebuffer.FrameProbe(qmp, self.directory, drain)
        self.started = time.monotonic()
        self.current = None
        self.last = None
        self.samples, self.operations = [], []

    def read(self):
        sample = self.ram.read()
        sample.update(stage=self.current, relative=sample['end']-self.started)
        if sample['rgb_sha256'] != self.last:
            name = f'{len(self.samples):04d}.ppm'
            (self.directory/name).write_bytes(HEADER+self.framebuffer.framebuffer_rgb(self.ram.dump.read_bytes()))
            sample['frame'] = name
            self.last = sample['rgb_sha256']
        self.samples.append(sample)

    def begin(self, stage):
        if self.current is not None or stage != STAGES[len(self.operations)]:
            raise ValueError('overlapping or reordered keyboard operation')
        self.current, self.last = stage, None
        self.operations.append(dict(stage=stage, begin=time.monotonic()-self.started))
        self.read()

    def finish(self):
        if self.current is None:
            return
        self.read()
        self.operations[-1]['end'] = time.monotonic()-self.started
        self.current = None

    def wait(self, seconds):
        if self.current is None or seconds <= 0:
            return self.drain(seconds)
        until = time.monotonic()+seconds
        while time.monotonic() < until:
            self.read()
            self.drain(min(.008, max(0, until-time.monotonic())))

    def save(self):
        (self.out/'keyboard-motion-samples.json').write_text(json.dumps(dict(
            scope='guest RAM during real keyboard input; no screendump or stop/cont during sampling',
            observer_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            registers=self.ram.registers, samples=self.samples, operations=self.operations),indent=2)+'\n')


def summarize(data, frames):
    samples, operations = data['samples'], data['operations']
    if tuple(o['stage'] for o in operations) != STAGES or any('end' not in o for o in operations):
        raise ValueError('incomplete keyboard transition sequence')
    if any(o['end']-o['begin'] < 1.5 for o in operations):
        raise ValueError('keyboard transition observation too short')
    if any(a['end'] > b['begin'] for a,b in zip(operations,operations[1:])):
        raise ValueError('overlapping keyboard observations')
    if not samples or any(a['end'] >= b['end'] for a,b in zip(samples,samples[1:])):
        raise ValueError('missing or non-monotonic keyboard observations')
    order = []
    for sample in samples:
        if not order or order[-1] != sample['stage']: order.append(sample['stage'])
    if tuple(order) != STAGES:
        raise ValueError('missing or reordered keyboard transition samples')
    results = {}
    for stage, operation in zip(STAGES,operations):
        rows = [s for s in samples if s['stage'] == stage]
        if len(rows) < 20 or rows[0]['relative'] > operation['begin']+.25 or operation['end']-rows[-1]['relative'] > .25:
            raise ValueError('incomplete keyboard transition coverage')
        last_hash = None
        black_pixels = None
        maximum_black = 0
        black_samples = excessive_black = 0
        for row in rows:
            if row['relative'] < operation['begin'] or row['relative'] > operation['end']:
                raise ValueError('keyboard sample outside its operation')
            if 'frame' in row:
                ppm = frames[row['frame']]
                if len(ppm) != len(HEADER)+PIXELS*3 or not ppm.startswith(HEADER):
                    raise ValueError('incomplete keyboard RGB frame')
                rgb = ppm[len(HEADER):]
                last_hash = hashlib.sha256(rgb).hexdigest()
                black_pixels = sum(r == g == b == 0 for r,g,b in zip(rgb[0::3],rgb[1::3],rgb[2::3]))
            if row['rgb_sha256'] != last_hash:
                raise ValueError('keyboard RAM sample has no matching saved frame')
            black_samples += row['rgb_sha256'] == BLACK
            maximum_black = max(maximum_black, black_pixels)
            # Notes-specific gate. Normal paper/list/keyboard states use less
            # than 10% pure black. Reject large partial clears as well as full
            # black frames; never use this rule to filter the actual display.
            excessive_black += black_pixels > PIXELS//5
        results[stage] = dict(samples=len(rows),black_samples=black_samples,
            excessive_black_samples=excessive_black,maximum_black_pixels=maximum_black,
            observed_seconds=rows[-1]['end']-rows[0]['start'])
    return dict(stages=results,passed=all(not r['excessive_black_samples'] for r in results.values()),
        scope='sampled Notes keyboard show/hide; large black area gate is Notes-specific, not FPS or all-app acceptance')


def analyze(out):
    data = json.loads((out/'keyboard-motion-samples.json').read_text())
    frames = {row['frame']:(out/'keyboard-motion'/row['frame']).read_bytes()
              for row in data['samples'] if 'frame' in row}
    return summarize(data,frames)
