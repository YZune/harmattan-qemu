"""Local experiment: native-window file events to the existing QMP owner.

No listener, socket, guest-file text editing, or replacement guest UI. Input is
accepted only after the caller's unchanged strict Home startup gates. Captures
are QMP RGB PPMs exported without visual changes. A capture pauses the VM only
for screendump; conversion occurs after cont. This is not a display-FPS probe.
"""
from collections import deque
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
import threading
import time

WIDTH, HEIGHT = 480, 864
CAPTURE_HZ = 18
FRAME_PERIOD = 1 / CAPTURE_HZ
IDLE_POLL_SECONDS = .005
NAME = re.compile(r'([A-Za-z0-9_-]{8,64})\.(\d{20})\.json\Z')
MAX_EVENTS = 256
MAX_KEY_PHASES = 128
MAX_EVENT_AGE_SECONDS = 8
HEARTBEAT_SECONDS = 3
HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('live_keyboard', HERE / 'arm64-keyboard.py')
keyboard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(keyboard)
LAYOUTS = {keyboard.LAYOUT_RGB['editor']: 'upper',
           keyboard.LAYOUT_RGB['deleted']: 'lower',
           keyboard.LAYOUT_RGB['symbols']: 'symbols'}
KEYS = {c: (24 + 48 * i, 590) for i, c in enumerate('qwertyuiop')}
KEYS.update({c: (48 + 48 * i, 670) for i, c in enumerate('asdfghjkl')})
KEYS.update({c: (96 + 48 * i, 750) for i, c in enumerate('zxcvbnm')})
KEYS.update({'Backspace': (449, 750), 'Enter': (423, 825),
             ' ': (239, 825), ',': (144, 825), '.': (336, 825)})


def next_capture_deadline(started, finished):
    """No extra post-encode period and no catch-up burst after an overrun."""
    return max(started + FRAME_PERIOD, finished)


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_name('.' + path.name + '.' + secrets.token_hex(6))
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(value, stream, ensure_ascii=True, separators=(',', ':'), allow_nan=False)
            stream.write('\n')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def private_directory(path):
    path = Path(path).absolute()
    # mkdir is the ownership claim. Never reuse a previous controller's queue
    # or delete a failed session: its evidence belongs to the caller.
    try:
        path.mkdir(mode=0o700, parents=True)
    except FileExistsError as error:
        raise ValueError('bridge directory already exists; choose a fresh session path') from error
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError('bridge directory must be an owned, nonsymlink mode-0700 directory')
    return path


def read_event(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_size > 4096:
            raise ValueError('event must be an owned regular file no larger than 4096 bytes')
        value = json.loads(stream.read(4097))
    if not isinstance(value, dict):
        raise ValueError('event must be a JSON object')
    return value


def pointer_events(x, y, down):
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or
           (isinstance(v, float) and not math.isfinite(v)) for v in (x, y)):
        raise ValueError('pointer coordinates must be finite numbers')
    if not 0 <= x <= WIDTH - 1 or not 0 <= y <= HEIGHT - 1:
        raise ValueError('pointer outside 480x864 guest surface')
    return [{'type': 'abs', 'data': {'axis': 'x', 'value': round(x * 32767 / (WIDTH - 1))}},
            {'type': 'abs', 'data': {'axis': 'y', 'value': round(y * 32767 / (HEIGHT - 1))}},
            {'type': 'btn', 'data': {'button': 'left', 'down': down}}]


class StartupCancelled(RuntimeError):
    """A validated native Quit was received before guest readiness."""


class Session:
    def __init__(self, directory, metrics=False):
        self.directory = private_directory(directory)
        self.events = private_directory(self.directory / 'events')
        self.metrics_enabled = metrics
        self.key_timings = {} if metrics else None
        self.controller_id = secrets.token_hex(16)
        self.publish_lock = threading.RLock()
        self.heartbeat_stop = threading.Event()
        self.heartbeat_thread = None
        self.acks = {}
        self.down = False
        self.point = (0, 0)
        self.pointer_client = None
        self.pointer_updated = 0
        self.press_started = 0
        self.pending = None
        self.steps = deque()
        # A contact can outlive its cancelled request in Maliit's event loop.
        # Keep only a passive visual guard, never a key or a replayable action.
        self.layout_transition = None
        self.next_step = 0
        self.qmp = None
        self.next_frame = 0
        self.next_status = 0
        self.next_validate = 0
        self.next_resources = 0
        self.capture_started = None
        self.loop_metrics = {'loops': 0, 'drain_ms': 0.0, 'validation_ms': 0.0,
                             'input_qmp_ms': 0.0, 'queue_reads_ms': 0.0}
        self.queue_depth = 0
        self.state = {'v': 1, 'controller_id': self.controller_id, 'state': 'starting',
                      'ready': False, 'width': WIDTH, 'height': HEIGHT, 'frame_counter': 0,
                      'frame_updated_ms': 0, 'event_ack': 0, 'event_client_id': '',
                      'error': '', 'key_error': '', 'event_result': '', 'keyboard_layout': 'unknown',
                      'input_source': 'native frontend event files to owned QMP stdio',
                      'capture_scope': 'actual framebuffer; sampled captures, not display FPS',
                      'capture_target_hz': CAPTURE_HZ}
        self.publish()

    def set_storage(self, *, mode, previous_exit_unclean):
        """Publish host storage policy; never claims guest recovery or save success."""
        if (mode not in ('disposable', 'persistent') or type(previous_exit_unclean) is not bool or
                (mode == 'disposable' and previous_exit_unclean)):
            raise ValueError('invalid storage notice')
        with self.publish_lock:
            self.state['storage'] = {'mode': mode, 'previous_exit_unclean': previous_exit_unclean}
            self.publish()

    def metric(self, kind, **values):
        """Task-local timing; does not drive readiness or input decisions."""
        if not self.metrics_enabled:
            return
        with (self.directory / 'performance.jsonl').open('a') as stream:
            stream.write(json.dumps({'kind': kind, 'controller_id': self.controller_id,
                                     'unix_ms': time.time_ns() / 1e6,
                                     'mono_ns': time.monotonic_ns(), **values}) + '\n')

    def key_timing(self, event):
        """Bounded, text-free observations; never consulted by input decisions."""
        if not self.metrics_enabled or event.get('type') != 'key':
            return None
        identity = (event['client_id'], event['seq'])
        if identity not in self.key_timings:
            # At most the bounded file queue plus the currently serviced key.
            if len(self.key_timings) >= MAX_EVENTS + 1:
                return None
            self.key_timings[identity] = {
                'input_kind': 'escape_gesture' if event.get('key') == 'Escape' else 'keyboard',
                'observed_ns': time.monotonic_ns(), 'phases': [], 'dropped_phases': 0,
            }
        return self.key_timings[identity]

    def key_phase(self, event, phase, at=None):
        timing = self.key_timing(event)
        if timing is None:
            return
        at = time.monotonic_ns() if at is None else at
        if len(timing['phases']) < MAX_KEY_PHASES:
            timing['phases'].append({'phase': phase, 'mono_ns': at})
        else:
            timing['dropped_phases'] += 1
        if phase.endswith('_started'):
            timing[phase + '_ns'] = at
        elif phase.endswith('_finished'):
            name = phase.removesuffix('_finished')
            started = timing.pop(name + '_started_ns', None)
            if started is not None:
                timing[name + '_ns'] = timing.get(name + '_ns', 0) + at - started

    def finish_key_timing(self, identity, outcome):
        if not self.metrics_enabled:
            return
        timing = self.key_timings.pop(identity, None)
        if timing is None:
            return
        completed = time.monotonic_ns()
        started = timing.get('service_started_ns')
        completion_started = timing.get('completion_started_ns')
        durations = {'queue_wait': None if started is None else (started - timing['observed_ns']) / 1e6,
                     'service': None if started is None else (completed - started) / 1e6,
                     'touchdown_qmp': timing.get('touchdown_ns', 0) / 1e6,
                     'touchup_qmp': timing.get('touchup_ns', 0) / 1e6,
                     'completion': None if completion_started is None else (completed - completion_started) / 1e6}
        for name in ('layout_wait', 'case_switch'):
            elapsed = timing.get(name + '_ns', 0)
            if name + '_started_ns' in timing:
                elapsed += (completed if completion_started is None else completion_started) - timing[name + '_started_ns']
            durations[name] = elapsed / 1e6
        self.metric('keyboard', client_id=identity[0], event_sequence=identity[1],
                    input_kind=timing['input_kind'], outcome=outcome,
                    observed_ns=timing['observed_ns'], service_started_ns=started,
                    completed_ns=completed, durations_ms=durations,
                    phases=timing['phases'], dropped_phases=timing['dropped_phases'])

    def finish_key_timings(self):
        if self.metrics_enabled:
            try:
                for identity in list(self.key_timings):
                    self.finish_key_timing(identity, 'interrupted')
            finally:
                self.key_timings.clear()

    def resources(self):
        if not self.metrics_enabled:
            return
        samples = {}
        for name, pid in (('controller', os.getpid()), ('qemu', getattr(self.qmp.process, 'pid', None))):
            if pid is None:
                continue
            try:
                fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
                samples[name] = {'pid': pid, 'cpu_ticks': int(fields[11]) + int(fields[12]),
                                 'rss_bytes': int(fields[21]) * os.sysconf('SC_PAGE_SIZE')}
            except (OSError, ValueError, IndexError):
                pass
        self.metric('resources', tick_hz=os.sysconf('SC_CLK_TCK'), samples=samples)
        self.next_resources = time.monotonic() + 1

    def publish(self):
        with self.publish_lock:
            self.state['updated_ms'] = round(time.time() * 1000)
            self.state['pointer_down'] = self.down
            # A detached snapshot avoids a partial read if the owner changes
            # its state while the startup-only heartbeat writes status.
            atomic_json(self.directory / 'status.json', self.state.copy())
            self.next_status = time.monotonic() + .2

    def start_startup_heartbeat(self):
        if self.heartbeat_thread is not None:
            raise RuntimeError('startup heartbeat already started')
        def heartbeat():
            while not self.heartbeat_stop.wait(.5):
                if self.state['state'] != 'starting':
                    break
                self.publish()
        self.heartbeat_thread = threading.Thread(target=heartbeat, name='startup-status', daemon=True)
        self.heartbeat_thread.start()

    def stop_startup_heartbeat(self):
        self.heartbeat_stop.set()
        if self.heartbeat_thread is not None:
            self.heartbeat_thread.join(timeout=2)
            if self.heartbeat_thread.is_alive():
                raise RuntimeError('startup status writer did not stop')

    def finish(self, passed=False, **extra):
        self.stop_startup_heartbeat()
        self.state.update(dict(ready=False, state='exited' if passed else 'error', passed=passed) | extra)
        self.publish()
        self.finish_key_timings()

    def pointer(self, x, y, down, client=None, timing_event=None):
        payload = pointer_events(x, y, down)
        timing_event = self.pending if timing_event is None else timing_event
        timing = self.key_timing(timing_event) if timing_event else None
        phase = None
        if timing is not None and down != self.down:
            phase = ('case_switch_' if 'case_switch_started_ns' in timing else '') + ('touchdown' if down else 'touchup')
        started = time.monotonic_ns() if phase else None
        begin = time.perf_counter_ns()
        succeeded = False
        try:
            self.qmp.call('input-send-event', {'events': payload})
            succeeded = True
        finally:
            if phase:
                finished = time.monotonic_ns()
                self.key_phase(timing_event, phase + '_started', started)
                self.key_phase(timing_event, phase + ('_finished' if succeeded else '_failed'), finished)
        self.loop_metrics['input_qmp_ms'] += (time.perf_counter_ns() - begin) / 1e6
        if down and not self.down:
            self.press_started = time.monotonic()
        self.point, self.down = (x, y), down
        self.pointer_client = client if down else None
        self.pointer_updated = time.monotonic()
        if not down and self.layout_transition is not None and self.layout_transition['frame'] is None:
            self.layout_transition.update(frame=self.state['frame_counter'], expires=time.monotonic() + 2)

    def release(self, timing_event=None):
        if self.down:
            self.pointer(*self.point, False, timing_event=timing_event)

    def confirm_layout_transition(self):
        transition = self.layout_transition
        if transition is None:
            return True
        # Old known frames and fresh opposite-case frames do not establish
        # that the guest processed the released contact, even after cancel.
        if (transition['frame'] is not None and self.state['frame_counter'] > transition['frame'] and
                self.state['keyboard_layout'] == transition['layout']):
            self.layout_transition = None
            return True
        return False

    def capture(self):
        from PIL import Image
        cadence_started = time.monotonic()
        capture_started_ns = time.monotonic_ns() if self.metrics_enabled else None
        marks = [('start', time.perf_counter_ns())]
        started_ms = time.time_ns() / 1e6
        interval_ms = None if self.capture_started is None else (marks[0][1] - self.capture_started) / 1e6
        self.capture_started = marks[0][1]
        ppm = self.directory / ('.frame.' + self.controller_id + '.ppm')
        png = self.directory / ('.frame.' + self.controller_id + '.png')
        self.qmp.call('stop')
        marks.append(('stop', time.perf_counter_ns()))
        try:
            self.qmp.call('screendump', {'filename': str(ppm), 'format': 'ppm'})
            sampled_ns = time.monotonic_ns() if self.metrics_enabled else None
            marks.append(('dump', time.perf_counter_ns()))
        finally:
            self.qmp.call('cont')
        marks.append(('cont', time.perf_counter_ns()))
        with Image.open(ppm) as original:
            original.load()
            if original.format != 'PPM' or original.mode != 'RGB' or original.size != (WIDTH, HEIGHT):
                raise ValueError('QMP frame must be original upright 480x864 RGB PPM')
            pixels = original.tobytes()
            marks.append(('ppm_load', time.perf_counter_ns()))
            original.save(png, format='PNG', compress_level=1)
        marks.append(('png_encode', time.perf_counter_ns()))
        with Image.open(png) as exported:
            exported.load()
            if exported.mode != 'RGB' or exported.size != (WIDTH, HEIGHT) or exported.tobytes() != pixels:
                raise ValueError('live PNG changed original framebuffer pixels')
        marks.append(('png_verify', time.perf_counter_ns()))
        # A paused/held key has a transient key cap; do not guess its layout.
        digest = hashlib.sha256(pixels[550 * WIDTH * 3:]).hexdigest()
        self.state['keyboard_layout'] = LAYOUTS.get(digest, 'unknown')
        provenance = {'frame_counter': self.state['frame_counter'] + 1, 'dimensions': [WIDTH, HEIGHT],
                      'source': 'frame.ppm', 'export': 'frame.png', 'pixel_bytes_identical': True,
                      'source_sha256': hashlib.sha256(ppm.read_bytes()).hexdigest(),
                      'png_sha256': hashlib.sha256(png.read_bytes()).hexdigest(),
                      'rgb_sha256': hashlib.sha256(pixels).hexdigest(),
                      'operation': 'QMP PPM to lossless PNG; no visual edits'}
        marks.append(('hashes', time.perf_counter_ns()))
        os.replace(ppm, self.directory / 'frame.ppm')
        frame_name = 'frame.%020d.png' % provenance['frame_counter']
        immutable = self.directory / frame_name
        os.replace(png, immutable)
        # Hard links share immutable bytes; readers holding either old inode
        # can finish while this name atomically switches to the new capture.
        os.link(immutable, png)
        os.replace(png, self.directory / 'frame.png')
        atomic_json(self.directory / 'frame.provenance.json', provenance)
        self.state.update(frame_counter=provenance['frame_counter'], frame_file=frame_name, frame_updated_ms=round(time.time() * 1000),
                          rgb_sha256=provenance['rgb_sha256'])
        if self.pending is None:
            # Remember a cancelled contact settling while idle, even if the
            # user changes views before their next text request. This only
            # clears a passive guard; it never resumes the cancelled action.
            self.confirm_layout_transition()
        # Start-to-start pacing: encoding is work inside the frame budget.
        # Skip missed slots rather than bursting captures after a long operation.
        self.next_frame = next_capture_deadline(cadence_started, time.monotonic())
        self.publish()
        for old in sorted(self.directory.glob('frame.[0-9]*.png'))[:-3]:
            if re.fullmatch(r'frame\.\d{20}\.png', old.name):
                old.unlink(missing_ok=True)
        marks.append(('publish', time.perf_counter_ns()))
        self.metric('capture', frame_counter=provenance['frame_counter'], started_ms=started_ms,
                    capture_started_ns=capture_started_ns, sampled_ns=sampled_ns,
                    keyboard_layout=self.state['keyboard_layout'],
                    interval_ms=interval_ms, total_ms=(marks[-1][1] - marks[0][1]) / 1e6,
                    stages_ms={marks[i][0]: (marks[i][1] - marks[i-1][1]) / 1e6
                               for i in range(1, len(marks))}, queue_depth=self.queue_depth,
                    loop_totals=self.loop_metrics.copy())
        self.loop_metrics = dict.fromkeys(self.loop_metrics, 0.0)

    def acknowledge(self, event, accepted, message=''):
        self.key_phase(event, 'completion_started')
        client, sequence = event['client_id'], event['seq']
        self.acks[client] = max(sequence, self.acks.get(client, 0))
        self.state.update(event_client_id=client, event_ack=self.acks[client],
                          event_result='accepted' if accepted else 'rejected')
        if message:
            self.state['key_error'] = message
        elif event.get('type') == 'key':
            self.state['key_error'] = ''
        # Persist protocol evidence, never the text the user typed or arbitrary
        # extra payload fields. Even rejected/malformed input is allowlisted.
        record = {name: event[name] for name in ('controller_id', 'client_id', 'seq') if name in event}
        record['type'] = event.get('type') if event.get('type') in ('key', 'pointer', 'release', 'cancel', 'quit') else 'invalid'
        if type(event.get('created_ms')) is int:
            record['created_ms'] = event['created_ms']
        if event.get('action') in ('down', 'move', 'up'):
            record['action'] = event['action']
        for name, limit in (('x', WIDTH), ('y', HEIGHT)):
            if type(event.get(name)) in (int, float) and 0 <= event[name] < limit:
                record[name] = event[name]
        if 'key' in event:
            record['key'] = '[redacted]'
        with (self.directory / 'input-audit.jsonl').open('a') as audit:
            audit.write(json.dumps({'time_ms': round(time.time() * 1000), 'event': record,
                                    'accepted': accepted, 'message': message}) + '\n')
        self.publish()
        self.finish_key_timing((client, sequence), 'accepted' if accepted else 'rejected')

    def event_paths(self):
        begin = time.perf_counter_ns()
        paths = sorted(self.events.glob('*.json'))
        self.queue_depth = len(paths)
        self.loop_metrics['queue_reads_ms'] += (time.perf_counter_ns() - begin) / 1e6
        if len(paths) > MAX_EVENTS:
            raise ValueError('native event queue exceeds 256 files; stop to avoid stale input replay')
        if any(not NAME.fullmatch(path.name) for path in paths):
            raise ValueError('invalid event filename in private queue')
        if self.metrics_enabled:
            present = {(match[1], int(match[2])) for path in paths if (match := NAME.fullmatch(path.name))}
            if self.pending:
                present.add((self.pending['client_id'], self.pending['seq']))
            for identity in self.key_timings.keys() - present:
                self.finish_key_timing(identity, 'removed')
        return paths

    def read_queued_event(self, path):
        match = NAME.fullmatch(path.name)
        client, sequence = match[1], int(match[2])
        event = read_event(path)
        if (event.get('controller_id') != self.controller_id or event.get('client_id') != client or
                type(event.get('seq')) is not int or event['seq'] != sequence or sequence < 1):
            raise ValueError('event identity does not match this controller and filename')
        if client not in self.acks and len(self.acks) >= 8:
            raise ValueError('too many frontend clients for this session')
        # First bridge observation is a monotonic queue boundary, not the
        # frontend's wall-clock created_ms or its unrelated ticks epoch.
        self.key_timing(event)
        return event

    def heartbeat_fresh(self, client):
        heartbeat = self.directory / ('heartbeat.' + client + '.json')
        try:
            data = read_event(heartbeat)
            now = time.time()
            return (data.get('controller_id') == self.controller_id and
                    data.get('client_id') == client and type(data.get('updated_ms')) is int and
                    0 <= int(now * 1000) - data['updated_ms'] <= HEARTBEAT_SECONDS * 1000 and
                    0 <= now - heartbeat.stat().st_mtime <= HEARTBEAT_SECONDS)
        except (OSError, ValueError):
            return False

    def validate_event(self, event):
        client, sequence = event.get('client_id'), event.get('seq')
        if (event.get('controller_id') != self.controller_id or not isinstance(client, str) or
                not re.fullmatch(r'[A-Za-z0-9_-]{8,64}', client) or
                type(sequence) is not int or sequence < 1):
            raise ValueError('invalid event identity')
        created = event.get('created_ms')
        if type(created) is not int or created < 0:
            raise ValueError('event created_ms must be a nonnegative integer timestamp')
        age_ms = int(time.time() * 1000) - created
        if age_ms < 0:
            raise ValueError('event timestamp is in the future')
        kind = event.get('type')
        if kind in ('release', 'cancel', 'quit'):
            # Safety controls can cancel a stale backlog, but still require a
            # valid timestamp, controller identity, and contiguous sequence.
            return
        if age_ms > MAX_EVENT_AGE_SECONDS * 1000:
            raise ValueError('input event expired; stale input is never replayed')
        if kind == 'pointer':
            if event.get('action') not in ('down', 'move', 'up'):
                raise ValueError('unknown pointer action')
            pointer_events(event.get('x'), event.get('y'), event['action'] != 'up')
        elif kind == 'key':
            key = event.get('key')
            if not isinstance(key, str) or len(key) > 32:
                raise ValueError('invalid key')
            if key not in KEYS and key != 'Escape' and not (len(key) == 1 and key.isascii() and key.isalpha()):
                raise ValueError('unsupported key; use the original on-screen keyboard for symbols or other layouts')
        else:
            raise ValueError('unsupported event type')
        if not self.heartbeat_fresh(client):
            raise ValueError('frontend heartbeat lost; input rejected')

    def cancel_pending(self, message):
        event, self.pending = self.pending, None
        self.steps.clear()
        self.release(timing_event=event)
        if event is not None:
            self.acknowledge(event, False, message)

    def urgent_event(self, paths, kinds=('cancel', 'quit')):
        """Cancel a contiguous same-client prefix, never execute out of order.

        Only a fully validated control event can preempt input. Every earlier
        sequence must be present and have matching file/payload identities;
        their payloads are rejected without ever becoming guest actions.
        """
        prefixes = {}
        blocked = set()
        for path in paths:
            match = NAME.fullmatch(path.name)
            client, sequence = match[1], int(match[2])
            previous = self.acks.get(client, 0)
            if client in blocked or sequence <= previous:
                continue
            prefix = prefixes.setdefault(client, [])
            pending = self.pending if self.pending and self.pending['client_id'] == client else None
            expected = previous + 1 + len(prefix) + (1 if pending else 0)
            if (pending and pending['seq'] != previous + 1) or sequence != expected:
                blocked.add(client)
                continue
            try:
                event = self.read_queued_event(path)
            except (ValueError, OSError):
                blocked.add(client)
                continue
            if event.get('type') in kinds:
                try:
                    self.validate_event(event)
                except ValueError:
                    blocked.add(client)
                    continue
                message = 'input cancelled by native ' + event['type']
                if pending:
                    self.cancel_pending(message)
                for earlier_path, earlier in prefix:
                    earlier_path.unlink()
                    self.acknowledge(earlier, False, message)
                path.unlink()
                return event
            prefix.append((path, event))
        return None

    def next_event(self):
        paths = self.event_paths()
        urgent = self.urgent_event(paths)
        if urgent is not None:
            return urgent
        if self.pending:
            return None
        for path in paths:
            match = NAME.fullmatch(path.name)
            client, sequence = match[1], int(match[2])
            event = None
            try:
                event = self.read_queued_event(path)
                previous = self.acks.get(client, 0)
                if sequence <= previous:
                    raise ValueError('duplicate or replayed input event')
                if sequence != previous + 1:
                    raise ValueError('input sequence gap; release and reject instead of reordering')
                self.validate_event(event)
                path.unlink()
                return event
            except (ValueError, OSError, json.JSONDecodeError) as error:
                self.release()
                # Wrong-controller events must never advance this controller's
                # counters; retain only diagnostic text in the current status.
                if event is not None:
                    self.acknowledge(event, False, str(error))
                else:
                    self.state['key_error'] = str(error)
                    self.publish()
                path.unlink(missing_ok=True)
        return None

    def check_startup_cancel(self):
        if self.state['state'] != 'starting':
            return
        event = self.urgent_event(self.event_paths(), kinds=('quit',))
        if event is not None:
            self.begin(event)
            self.finish(False, state='cancelled', quit_reason='native frontend quit during startup')
            raise StartupCancelled('native frontend quit during startup')

    def begin(self, event):
        self.validate_event(event)
        kind = event.get('type')
        if self.pending and kind not in ('cancel', 'quit'):
            raise ValueError('pending input must finish or be cancelled before new input')
        previous = self.acks.get(event['client_id'], 0)
        pending_prefix = (kind in ('cancel', 'quit') and self.pending is not None and
                          self.pending['client_id'] == event['client_id'] and
                          self.pending['seq'] == previous + 1 and event['seq'] == previous + 2)
        if event['seq'] != previous + 1 and not pending_prefix:
            raise ValueError('input sequence gap; release and reject instead of reordering')
        if kind in ('cancel', 'quit') and self.pending:
            self.cancel_pending('input cancelled by native ' + kind)
        if kind == 'quit':
            self.release()
            self.acknowledge(event, True)
            self.state.update(ready=False, state='stopping', quit_reason='native frontend request')
            self.publish()
            return False
        if kind in ('release', 'cancel'):
            self.release()
        elif kind == 'pointer':
            action = event.get('action')
            if action not in ('down', 'move', 'up'):
                raise ValueError('unknown pointer action')
            if action == 'down' and self.down:
                raise ValueError('a pointer is already down')
            if action == 'move' and not self.down:
                raise ValueError('pointer move requires prior down')
            if self.down and self.pointer_client != event['client_id']:
                raise ValueError('pointer belongs to another frontend')
            if action == 'up' and self.down and time.monotonic() < self.press_started + .08:
                # Preserve a real minimum contact when down/up arrive together
                # after a capture. Otherwise a click can collapse between guest
                # touchscreen polls. Native movement remains ordered.
                pointer_events(event.get('x'), event.get('y'), False)
                self.pending = event
                self.steps = deque([('pointer', event['x'], event['y'], False, 0)])
                self.next_step = self.press_started + .08
                return True
            self.pointer(event.get('x'), event.get('y'), action != 'up', event['client_id'])
        elif kind == 'key':
            if self.down:
                raise ValueError('release pointer before keyboard input')
            key = event.get('key')
            if not isinstance(key, str) or len(key) > 32:
                raise ValueError('invalid key')
            self.pending = event
            self.key_phase(event, 'service_started')
            self.next_step = time.monotonic()
            if key == 'Escape':
                # Original edge-return gesture from arm64-keyboard.py. This
                # cannot be mistaken for a hardware Escape supported by guest.
                self.steps = deque([('pointer', 479, 420, True, .05)] +
                                   [('pointer', 479 - i * 21, 420, True, .05) for i in range(1, 21)] +
                                   [('pointer', 59, 420, False, 0)])
            else:
                if key not in KEYS and not (len(key) == 1 and key.isascii() and key.isalpha()):
                    self.pending = None
                    raise ValueError('unsupported key; use the original on-screen keyboard for symbols or other layouts')
                self.steps = deque([('key', key, time.monotonic() + 2)])
            return True
        else:
            raise ValueError('unsupported event type')
        self.acknowledge(event, True)
        return True

    def step(self):
        self.check_pointer_liveness()
        if not self.pending or time.monotonic() < self.next_step:
            return
        try:
            self.validate_event(self.pending)
        except ValueError as error:
            self.cancel_pending(str(error))
            return
        if not self.steps:
            self.acknowledge(self.pending, True)
            self.pending = None
            return
        item = self.steps.popleft()
        if item[0] in ('pointer', 'case_pointer'):
            _, x, y, down, delay, *target = item
            self.pointer(x, y, down, self.pending['client_id'])
            if target:
                self.layout_transition = {'layout': target[0], 'frame': None, 'expires': None}
            self.next_step = time.monotonic() + delay
            return
        settling = item[0] == 'settle'
        if settling:
            expires = self.layout_transition['expires']
            message = ('letter was released but keyboard case did not visibly settle; '
                       'text completion is uncertain and will not be replayed')
        else:
            _, key, expires = item
            message = ('keyboard case transition was not visibly confirmed; text input not sent'
                       if self.layout_transition is not None or item[0] == 'case' else
                       'original letter keyboard is not visibly recognized; open it before typing')
        if time.monotonic() >= expires:
            self.cancel_pending(message)
            return
        timing = self.key_timing(self.pending)
        layout = self.state['keyboard_layout']
        if not self.confirm_layout_transition():
            self.wait_layout(item)
            return
        if layout not in ('upper', 'lower') or (item[0] == 'case' and (layout == 'upper') != key.isupper()):
            self.wait_layout(item)
            return
        if timing is not None and 'layout_wait_started_ns' in timing:
            self.key_phase(self.pending, 'layout_wait_finished')
        if settling:
            self.acknowledge(self.pending, True)
            self.pending = None
            return
        if item[0] == 'case':
            self.key_phase(self.pending, 'case_switch_finished')
        alpha = len(key) == 1 and key.isascii() and key.isalpha()
        if alpha and ((layout == 'upper') != key.isupper()):
            self.key_phase(self.pending, 'case_switch_started')
            desired = 'upper' if key.isupper() else 'lower'
            # The case step can only wait or send the letter. Never toggle
            # Shift again because the old hash persists after its cooldown.
            self.steps.extendleft(reversed([('case_pointer', 32, 750, True, .10, desired),
                                            ('pointer', 32, 750, False, .30),
                                            ('case', key, expires)]))
        else:
            x, y = KEYS[key.lower() if alpha else key]
            contact = ('pointer', x, y, True, .10)
            if alpha and key.isupper():
                contact = ('case_pointer', x, y, True, .10, 'lower')
            self.steps.extendleft(reversed([contact, ('pointer', x, y, False, .18)] +
                                          ([('settle',)] if alpha and key.isupper() else [])))

    def wait_layout(self, item):
        timing = self.key_timing(self.pending)
        if timing is not None and 'layout_wait_started_ns' not in timing:
            self.key_phase(self.pending, 'layout_wait_started')
        self.steps.appendleft(item)
        self.next_step = time.monotonic() + .05

    def check_pointer_liveness(self):
        clients = set()
        if self.pending:
            clients.add(self.pending['client_id'])
        if self.down:
            clients.add(self.pointer_client)
        if any(not self.heartbeat_fresh(client) for client in clients):
            self.cancel_pending('frontend heartbeat lost; pending input cancelled and touch released')
            self.release()
            self.state['key_error'] = 'frontend heartbeat lost; touch released'
            self.publish()

    def wait_seconds(self, now):
        """Poll input promptly without sleeping through capture/key deadlines."""
        due = [self.next_frame, self.next_status, self.next_validate]
        if self.metrics_enabled:
            due.append(self.next_resources)
        if self.pending:
            due.append(self.next_step)
        return max(0, min(IDLE_POLL_SECONDS, min(due) - now))

    def run(self, qmp, drain, deadline, validate_live):
        self.stop_startup_heartbeat()
        self.qmp = qmp
        self.state.update(ready=True, state='ready')
        self.capture()
        try:
            while qmp.process.poll() is None:
                self.loop_metrics['loops'] += 1
                now = time.monotonic()
                qmp.deadline = min(deadline + 10, now + 5)
                if now >= deadline:
                    self.state.update(ready=False, state='stopping', quit_reason='bounded session timeout')
                    self.publish()
                    break
                self.check_pointer_liveness()
                # Look for validated safety controls before a pending key can
                # make another contact, including while waiting for Maliit.
                for _ in range(32):
                    event = self.next_event()
                    if event is None:
                        break
                    try:
                        if not self.begin(event):
                            return
                    except ValueError as error:
                        self.cancel_pending(str(error))
                        self.acknowledge(event, False, str(error))
                    if self.pending or event.get('type') == 'pointer':
                        break
                self.step()
                now = time.monotonic()
                if now >= self.next_frame:
                    self.capture()
                if now >= self.next_status:
                    self.publish()
                if now >= self.next_validate:
                    begin = time.perf_counter_ns()
                    validate_live()
                    self.loop_metrics['validation_ms'] += (time.perf_counter_ns() - begin) / 1e6
                    self.next_validate = now + 2
                if self.metrics_enabled and now >= self.next_resources:
                    self.resources()
                begin = time.perf_counter_ns()
                drain(self.wait_seconds(time.monotonic()))
                self.loop_metrics['drain_ms'] += (time.perf_counter_ns() - begin) / 1e6
        finally:
            try:
                self.release()
                self.state['ready'] = False
                self.publish()
            finally:
                self.finish_key_timings()
