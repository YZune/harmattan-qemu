"""Own a Linux controller and its optional Godot window, using only local files.

Process exits describe lifecycle, never guest acceptance. The caller must still
check the controller's original startup/graphics/clean-exit result and base disk.
"""
import contextlib
import json
import math
import os
from pathlib import Path
import re
import select
import signal
import stat
import subprocess
import sys
import time


class SessionStatus:
    """Read only a new, owned bridge, pinning its directories and controller ID."""

    def __init__(self, directory, started_ms):
        self.directory = Path(directory)
        self.started_ms = started_ms
        self.identities = {}
        self.controller_id = None

    def read(self):
        for path in (self.directory, self.directory / 'events'):
            try:
                info = path.lstat()
            except FileNotFoundError:
                if path in self.identities:
                    raise ValueError('owned bridge directory disappeared')
                return None
            if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) != 0o700):
                raise ValueError('bridge directories must be owned, nonsymlink mode-0700 directories')
            identity = (info.st_dev, info.st_ino)
            if self.identities.setdefault(path, identity) != identity:
                raise ValueError('owned bridge directory was replaced')
        try:
            descriptor = os.open(self.directory / 'status.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except FileNotFoundError:
            return None
        with os.fdopen(descriptor, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 65536):
                raise ValueError('bridge status must be an owned mode-0600 regular file of at most 65536 bytes')
            status = json.loads(stream.read(65537))
        if not isinstance(status, dict):
            raise ValueError('bridge status must be an object')
        controller_id = status.get('controller_id')
        if not isinstance(controller_id, str) or re.fullmatch(r'[0-9a-f]{32}', controller_id) is None:
            raise ValueError('invalid bridge controller identity')
        if self.controller_id is not None and controller_id != self.controller_id:
            raise ValueError('bridge controller identity changed')
        updated = status.get('updated_ms')
        now = time.time() * 1000
        if (isinstance(updated, bool) or not isinstance(updated, (int, float))
                or not math.isfinite(updated) or updated < self.started_ms
                or not -1000 <= now - updated <= 3000):
            raise ValueError('bridge status is stale or has an invalid timestamp')
        if (status.get('v') != 1 or isinstance(status.get('v'), bool)
                or (status.get('width'), status.get('height')) != (480, 864)
                or not isinstance(status.get('ready'), bool)
                or status.get('state') not in ('starting', 'ready', 'stopping', 'exited', 'error', 'cancelled')):
            raise ValueError('invalid bridge status schema')
        self.controller_id = controller_id
        return status


def accepted_terminal(status):
    return (status is not None and status.get('state') == 'exited'
            and status.get('ready') is False and status.get('passed') is True
            and type(status.get('qemu_exit')) is int and status['qemu_exit'] == 0)


def stop_group(process, grace):
    """Reap the leader and kill surviving descendants even after leader exit."""
    if process is None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=5)


@contextlib.contextmanager
def interruption_handlers():
    previous = {number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGTERM)}
    def interrupted(number, unused_frame):
        raise InterruptedError(f'launcher received {signal.Signals(number).name}')
    try:
        for number in previous:
            signal.signal(number, interrupted)
        yield
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


def run(controller_command, controller_env, frontend_command, frontend_env,
        output, session, timeout, *, session_wait=15, frontend_grace=3, stop_grace=10):
    """Return lifecycle evidence after both owned process groups are stopped.

    A frontend that exits before a successful controller terminal status fails,
    even if its exit code is zero. A successful controller gets a short window
    for the frontend to observe its final status and exit normally.
    """
    output, session = Path(output), Path(session)
    if os.path.lexists(session):
        raise ValueError('bridge directory already exists; choose a fresh session path')
    controller = frontend = None
    result = {'frontend_started': False, 'controller_exit': None, 'frontend_exit': None,
              'frontend_stop': None, 'completed': False}
    with interruption_handlers(), contextlib.ExitStack() as files:
        try:
            log = files.enter_context((output / 'controller.log').open('xb'))
            frontend_log = files.enter_context((output / 'frontend.log').open('xb'))
            started_ms = int(time.time() * 1000)
            bridge = SessionStatus(session, started_ms)
            controller = subprocess.Popen(controller_command, env=controller_env,
                                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                          bufsize=0, start_new_session=True)
            result['controller_pid'] = controller.pid
            deadline = time.monotonic() + timeout
            session_deadline = min(deadline, time.monotonic() + session_wait)
            controller_done_at = frontend_done_at = None
            output_open = True
            while True:
                now = time.monotonic()
                if now >= deadline:
                    raise TimeoutError('Linux native controller exceeded its bounded runtime')
                controller_code = controller.poll()
                frontend_code = frontend.poll() if frontend is not None else None
                # Check the leader separately from pipe EOF: a crashed leader's
                # QEMU can otherwise keep its stdout open indefinitely.
                if controller_code is not None:
                    if controller_code != 0:
                        raise RuntimeError(f'Linux native controller exited with {controller_code}')
                    if frontend is None:
                        raise RuntimeError('controller exited before the native frontend started')
                    if controller_done_at is None:
                        if not accepted_terminal(bridge.read()):
                            raise RuntimeError('controller exited without successful terminal bridge status')
                        controller_done_at = now
                    if frontend_code is not None:
                        if frontend_code != 0:
                            raise RuntimeError(f'native frontend exited with {frontend_code}')
                        result.update(completed=True, frontend_stop='natural')
                        break
                    if now - controller_done_at >= frontend_grace:
                        raise TimeoutError('native frontend did not close after confirmed controller cleanup')
                elif frontend is not None and frontend_code is not None:
                    if frontend_code != 0:
                        raise RuntimeError(f'native frontend exited with {frontend_code}')
                    if frontend_done_at is None:
                        if not accepted_terminal(bridge.read()):
                            raise RuntimeError('native frontend closed before confirmed controller cleanup')
                        frontend_done_at = now
                    if now - frontend_done_at >= frontend_grace:
                        raise TimeoutError('controller did not exit after the native frontend closed')
                elif frontend is None:
                    if now >= session_deadline:
                        raise TimeoutError('controller did not publish a fresh native session in time')
                    status = bridge.read()
                    if status is not None:
                        if status['state'] not in ('starting', 'ready'):
                            raise RuntimeError('controller failed or stopped before the native frontend started')
                        result['controller_id'] = bridge.controller_id
                        frontend = subprocess.Popen(frontend_command, env=frontend_env,
                                                    stdout=frontend_log, stderr=subprocess.STDOUT,
                                                    start_new_session=True)
                        result.update(frontend_started=True, frontend_pid=frontend.pid)
                if output_open and select.select([controller.stdout], [], [], .05)[0]:
                    chunk = os.read(controller.stdout.fileno(), 65536)
                    if chunk:
                        log.write(chunk)
                        log.flush()
                        sys.stdout.buffer.write(chunk)
                        sys.stdout.buffer.flush()
                    else:
                        output_open = False
                elif not output_open:
                    time.sleep(.05)
        except (Exception, KeyboardInterrupt) as error:
            result['failure'] = f'{type(error).__name__}: {error}'
            result['frontend_stop'] = 'supervisor_cleanup' if frontend is not None else 'not_started'
        finally:
            # A second terminal interrupt must not skip either bounded cleanup.
            for number in (signal.SIGINT, signal.SIGTERM):
                signal.signal(number, signal.SIG_IGN)
            for name, process in (('frontend', frontend), ('controller', controller)):
                try:
                    stop_group(process, stop_grace)
                except Exception as error:
                    result['completed'] = False
                    result[f'{name}_cleanup_error'] = f'{type(error).__name__}: {error}'
                if process is not None:
                    result[f'{name}_exit'] = process.poll()
            if controller is not None:
                # All writers have now stopped. Preserve their final diagnostics
                # without depending on EOF from an inherited output descriptor.
                drain_deadline = time.monotonic() + 1
                while time.monotonic() < drain_deadline and select.select([controller.stdout], [], [], 0)[0]:
                    chunk = os.read(controller.stdout.fileno(), 65536)
                    if not chunk:
                        break
                    log.write(chunk)
                controller.stdout.close()
    return result
