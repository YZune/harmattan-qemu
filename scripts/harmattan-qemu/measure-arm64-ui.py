"""Bounded host CPU and guest framebuffer observations, not displayed FPS."""
import hashlib
import json
import os
import platform
import re
import subprocess
import time

WIDTH, HEIGHT = 864, 480
FRAME_BYTES = WIDTH * HEIGHT * 4
HOME_RGB = 'faf50b6a1720a06d434eb1d78d9ea49ece4480e1c525901851826d4a7c5217c4'


def clock_alignment():
    # On macOS Python uses mach_absolute_time(), while QEMU get_clock()
    # uses CLOCK_MONOTONIC. Their origins need not match. Bracket the
    # POSIX observation and retain the narrowest of seven samples.
    samples = []
    for _ in range(7):
        before = time.monotonic_ns()
        posix = time.clock_gettime_ns(time.CLOCK_MONOTONIC)
        after = time.monotonic_ns()
        middle = (before + after) // 2
        samples.append(dict(python_ns=middle, posix_ns=posix,
                            posix_minus_python_ns=posix - middle,
                            bracket_ns=after - before))
    return min(samples, key=lambda sample: sample['bracket_ns'])


def cpu_seconds(value):
    match = re.fullmatch(r'(?:(\d+)-)?(?:(\d+):)?(\d+):(\d+(?:\.\d+)?)', value)
    if not match:
        raise ValueError('unexpected ps CPU time')
    days, hours, minutes, seconds = match.groups()
    return int(days or 0) * 86400 + int(hours or 0) * 3600 + int(minutes) * 60 + float(seconds)


def parse_process(line, pid):
    fields = line.split()
    if len(fields) != 3 or int(fields[0]) != pid or int(fields[2]) <= 0:
        raise ValueError('missing or mismatched QEMU process sample')
    return {'pid': pid, 'cpu_seconds': cpu_seconds(fields[1]), 'rss_kib': int(fields[2])}


def sample_process(pid):
    start = time.monotonic()
    text = subprocess.check_output(['ps', '-p', str(pid), '-o', 'pid=,time=,rss='], text=True)
    end = time.monotonic()
    return {**parse_process(text, pid), 'monotonic_seconds': (start + end) / 2,
            'sampling_wall_seconds': end - start}


def summarize_cpu(samples):
    if len(samples) < 2 or len({s['pid'] for s in samples}) != 1:
        raise ValueError('CPU samples need one consistent process')
    walls = [s['monotonic_seconds'] for s in samples]
    cpus = [s['cpu_seconds'] for s in samples]
    if any(b <= a for a, b in zip(walls, walls[1:])) or any(b < a for a, b in zip(cpus, cpus[1:])):
        raise ValueError('non-monotonic CPU observations')
    wall = walls[-1] - walls[0]
    cpu = cpus[-1] - cpus[0]
    return {'wall_seconds': wall, 'cpu_seconds': cpu, 'one_core_percent': cpu / wall * 100,
            'rss_mib_range': [min(s['rss_kib'] for s in samples) / 1024,
                              max(s['rss_kib'] for s in samples) / 1024], 'samples': samples,
            'scope': 'process CPU delta / wall time; 100 percent means one CPU core, not the whole host'}


def summarize_threads(before, after):
    if (before['pid'] != after['pid'] or
            before['posix_after_ns'] >= after['posix_before_ns'] or
            before['posix_before_ns'] > before['posix_after_ns'] or
            after['posix_before_ns'] > after['posix_after_ns']):
        raise ValueError('invalid thread snapshot identity or time order')
    indexed = []
    for snapshot in (before, after):
        threads = {item['thread_handle']: item for item in snapshot['threads']}
        if not threads or len(threads) != len(snapshot['threads']):
            raise ValueError('empty or duplicated thread handles')
        indexed.append(threads)
    first, last = indexed
    matched = []
    for handle in first.keys() & last.keys():
        a, b = first[handle], last[handle]
        user = b['user_time_ns'] - a['user_time_ns']
        system = b['system_time_ns'] - a['system_time_ns']
        if user < 0 or system < 0 or a['name'] != b['name']:
            raise ValueError('thread counter regressed or identity changed')
        matched.append(dict(thread_handle=handle, name=b['name'], user_seconds=user / 1e9,
                            system_seconds=system / 1e9, cpu_seconds=(user + system) / 1e9,
                            priority_before=a['priority'], priority_after=b['priority']))
    matched.sort(key=lambda item: item['cpu_seconds'], reverse=True)
    return dict(scope='matched libproc thread CPU counters, not stack samples or core residency; boundary sampling is separate from frame latency',
                snapshots=[before, after], matched_threads=matched,
                matched_cpu_seconds=sum(item['cpu_seconds'] for item in matched),
                new_thread_handles=sorted(last.keys() - first.keys()),
                exited_thread_handles=sorted(first.keys() - last.keys()))


def validate_plane(registers):
    # Match the single RGB24-unpacked DPI plane actually implemented here.
    # Never accept an arbitrary guest MMIO address for a bulk memory read.
    address = registers['base']
    if not 0x80000000 <= address <= 0xa0000000 - FRAME_BYTES or address % 4:
        raise ValueError('framebuffer is not fully within aligned N00 SDRAM')
    if registers['size'] != ((HEIGHT - 1) << 16) | (WIDTH - 1):
        raise ValueError('unexpected framebuffer size')
    if registers['position'] or registers['row_inc'] != 1 or registers['pixel_inc'] != 1:
        raise ValueError('unsupported framebuffer layout')
    attr = registers['attributes']
    if not attr & 1 or (attr >> 1) & 15 != 8 or attr & (0x3600 | 0x100):
        raise ValueError('not the enabled RGB24-unpacked LCD plane')
    return address


def framebuffer_rgb(data):
    if len(data) != FRAME_BYTES:
        raise ValueError('truncated framebuffer RAM sample')
    rgb = bytearray(WIDTH * HEIGHT * 3)
    rgb[0::3], rgb[1::3], rgb[2::3] = data[2::4], data[1::4], data[0::4]
    return bytes(rgb)


class FrameProbe:
    def __init__(self, qmp, out, drain):
        self.qmp, self.out, self.drain = qmp, out, drain
        out.mkdir(parents=True, exist_ok=True)
        self.dump = out / 'performance-framebuffer.bin'
        if self.dump.exists():
            raise ValueError('framebuffer evidence already exists')
        self.registers = {}
        for name, offset in (('base', 0x80), ('position', 0x88), ('size', 0x8c),
                             ('attributes', 0xa0), ('row_inc', 0xac), ('pixel_inc', 0xb0)):
            address = 0x48050400 + offset
            reply = qmp.call('human-monitor-command', {'command-line': f'xp/1wx 0x{address:x}'})
            match = re.fullmatch(r'\s*([0-9a-fA-F]+): 0x([0-9a-fA-F]{8})\s*', reply)
            if not match or int(match[1], 16) != address:
                raise ValueError('unexpected DISPC register observation')
            self.registers[name] = int(match[2], 16)
        self.address = validate_plane(self.registers)

    def read(self):
        self.drain(0)
        start = time.monotonic()
        # pmemsave only copies this validated RAM span. Unlike screendump,
        # it does not request a DSS/Cocoa update or pause/resume the vCPU.
        self.qmp.call('pmemsave', {'val': self.address, 'size': FRAME_BYTES, 'filename': str(self.dump)})
        rgb = framebuffer_rgb(self.dump.read_bytes())
        digest = hashlib.sha256(rgb).hexdigest()
        end = time.monotonic()
        return {'start': start, 'end': end, 'rgb_sha256': digest, 'read_wall_seconds': end - start}

    def wait_for(self, digest, started, input_finished=None, timeout=25):
        samples = []
        deadline = min(started + timeout, self.qmp.deadline)
        while time.monotonic() < deadline:
            sample = self.read()
            samples.append(sample)
            if sample['rgb_sha256'] == digest:
                # This is first OBSERVED full-frame equality, not an exact
                # presentation timestamp. Reads may race guest drawing; only
                # a complete known RGB frame is accepted. No FPS inference.
                return {'first_observed_match_seconds': sample['end'] - started,
                        'input_duration_seconds': None if input_finished is None else input_finished - started,
                        'after_input_match_seconds': None if input_finished is None else sample['end'] - input_finished,
                        'nominal_poll_interval_seconds': 0.1,
                        'last_nonmatching_sample_seconds': None if len(samples) == 1 else samples[-2]['end'] - started,
                        'sample_count': len(samples), 'samples': samples,
                        'rgb_sha256': digest}
            self.drain(min(0.1, max(0, deadline - time.monotonic())))
        raise TimeoutError(f'no matching guest framebuffer {digest}; last samples: {samples[-2:]}')

    def wait_stable(self, digest, stable_seconds=0.6, timeout=10):
        # A first match may precede a transient scrollbar/fade. Preserve the
        # original first-observation time separately, then require a bounded
        # run of exact full-frame matches before the strict screenshot gate.
        started = time.monotonic()
        deadline = min(started + timeout, self.qmp.deadline)
        matching_since = None
        samples = []
        while time.monotonic() < deadline:
            sample = self.read()
            samples.append(sample)
            if sample['rgb_sha256'] == digest:
                if matching_since is None:
                    matching_since = sample['end']
                if sample['end'] - matching_since >= stable_seconds:
                    return {'required_stable_seconds': stable_seconds,
                            'observed_stable_seconds': sample['end'] - matching_since,
                            'wall_seconds': sample['end'] - started, 'samples': samples}
            else:
                matching_since = None
            self.drain(min(0.1, max(0, deadline - time.monotonic())))
        raise TimeoutError('reference did not remain stable before screenshot acceptance')


def run_probe(qmp, serial, wait_line, capture, display, rotation, out, process, drain, calculator):
    probe = FrameProbe(qmp, out, drain)
    if probe.read()['rgb_sha256'] != HOME_RGB:
        raise ValueError('live guest framebuffer differs from the verified Home reference')
    result = {'scope': 'host process CPU and first observed exact guest framebuffer; no native-window latency or FPS',
              'plane_registers': probe.registers, 'responses': {}, 'idle': {},
              'host': {'platform': platform.platform(), 'architecture': platform.machine(),
                       'logical_cpus': os.cpu_count(),
                       'cpu_brand': subprocess.check_output(['sysctl', '-n', 'machdep.cpu.brand_string'], text=True).strip()},
              'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'qemu_pid': process.pid}
    result['clock_alignment'] = {'start': clock_alignment()}
    result['trace_profile_enabled'] = os.environ.get('HARMATTAN_UI_PROFILE') == '1'
    thread_helper = os.environ.get('HARMATTAN_UI_THREAD_HELPER')
    if thread_helper:
        with open(thread_helper, 'rb') as stream:
            result['thread_helper_sha256'] = hashlib.file_digest(stream, 'sha256').hexdigest()

    def thread_snapshot():
        data = json.loads(subprocess.check_output([thread_helper, str(process.pid),
            os.path.realpath(process.args[0])], text=True, timeout=5))
        if data['pid'] != process.pid:
            raise ValueError('thread helper selected the wrong process')
        return data
    result_path = out / 'performance-measurements.json'

    def save():
        result_path.write_text(json.dumps(result, indent=2) + '\n')

    def idle(label):
        if qmp.call('query-status')['status'] != 'running':
            raise ValueError('QEMU not running before idle measurement')
        samples = [sample_process(process.pid)]
        for _ in range(3):
            drain(5)
            if process.poll() is not None:
                raise RuntimeError('QEMU exited during idle measurement')
            samples.append(sample_process(process.pid))
        if qmp.call('query-status')['status'] != 'running':
            raise ValueError('QEMU not running after idle measurement')
        result['idle'][label] = summarize_cpu(samples)
        save()
        print(f'MEASURE: {label} CPU={result["idle"][label]["one_core_percent"]:.1f}% of one core', flush=True)

    width, height = (480, 864) if rotation in (90, 270) else (864, 480)

    def pointer(px, py, down):
        x, y = display.surface_point(py, 479 - px, rotation)
        qmp.call('input-send-event', {'events': [
            {'type': 'abs', 'data': {'axis': 'x', 'value': round(x * 32767 / (width - 1))}},
            {'type': 'abs', 'data': {'axis': 'y', 'value': round(y * 32767 / (height - 1))}},
            {'type': 'btn', 'data': {'button': 'left', 'down': down}},
        ]})

    def tap(x, y):
        start = time.monotonic()
        pointer(x, y, True)
        drain(0.15)
        pointer(x, y, False)
        return start, time.monotonic()

    def swipe():
        start = time.monotonic()
        pointer(0, 420, True)
        for i in range(1, 21):
            drain(0.05)
            pointer(i * 21, 420, True)
        pointer(420, 420, False)
        return start, time.monotonic()

    def observe(stage):
        serial.sendall((f"printf '\\nN00_CALC_BEGIN_{stage}\\n'; "
                        "sh /tmp/n00-shell-guest.sh calculator-inspect; status=$?; "
                        f"printf '\\nN00_CALC_EXIT_{stage}_%s\\n' \"$status\"; "
                        f"printf '\\nN00_CALC_DONE_{stage}\\n'\n").encode())
        wait_line(f'N00_CALC_DONE_{stage}'.encode())
        # Outside the timed interval, retain the established paused screenshot
        # and real process/window identity gates for the same application.
        capture(f'calculator-{stage}')

    def response(name, target, times, stage):
        result['responses'][name] = probe.wait_for(target, *times[:2])
        result['responses'][name]['active_process'] = summarize_cpu([times[2], sample_process(process.pid)])
        if thread_helper:
            result['responses'][name]['host_threads'] = summarize_threads(times[3], thread_snapshot())
        save()
        print(f'MEASURE: {name} first matching guest frame in '
              f'{result["responses"][name]["first_observed_match_seconds"]:.3f}s from input start', flush=True)
        result['responses'][name]['reference_stability'] = probe.wait_stable(target)
        save()
        observe(stage)

    def measured_input(action):
        threads = thread_snapshot() if thread_helper else None
        before = sample_process(process.pid)
        return (*action(), before, threads)

    idle('home_before')
    observe('before')
    response('calculator_cold_open', calculator.ZERO_RGB, measured_input(lambda: tap(183, 692)), 'opened')
    idle('calculator_zero')
    for point in ((240, 680), (380, 330), (380, 680)):
        tap(*point)
        drain(0.4)
    response('equals_five', calculator.FIVE_RGB, measured_input(lambda: tap(380, 790)), 'sum')
    response('home_return_1', HOME_RGB, measured_input(swipe), 'returned')
    response('calculator_resume', calculator.FIVE_RGB, measured_input(lambda: tap(183, 692)), 'reopened')
    response('home_return_2', HOME_RGB, measured_input(swipe), 'final')
    idle('home_after')
    serial.sendall(b"sh -c 'sync && printf \"\\nN00_PERF_POST_IDLE_SYNC_OK\\n\"'\n")
    wait_line(b'N00_PERF_POST_IDLE_SYNC_OK')
    result['post_idle_sync'] = True
    result['clock_alignment']['end'] = clock_alignment()
    save()
    return result
