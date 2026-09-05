#!/usr/bin/env python3
"""Bounded private-snapshot scanout diagnostics; never change the normal launcher default."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time

CASES = {
    'baseline': ('0', '0', '--performance-diagnostic'),
    'timer-only': ('0', '1', '--performance-diagnostic'),
    'refresh-33ms': ('33', '0', '--performance-diagnostic'),
    'headless': ('0', '0', '--performance-headless-diagnostic'),
    'headless-background': ('0', '0', '--performance-headless-diagnostic'),
    'activity-off': ('0', '0', '--performance-diagnostic'),
    'activity-on': ('0', '0', '--performance-diagnostic'),
    'interaction-off': ('0', '0', '--performance-diagnostic'),
    'interaction-on': ('0', '0', '--performance-diagnostic'),
}


def background_private_child(controller, log_path, binary):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        output = log_path.read_text()
        if controller.poll() is not None:
            raise RuntimeError('controller exited before the scheduling probe')
        if 'DIAGNOSTIC: bootstrap exit=0;' in output:
            break
        time.sleep(.25)
    else:
        raise TimeoutError('bootstrap not reached for the scheduling probe')
    match = re.search(r'^Native UI run artifacts: (.+)$', output, re.MULTILINE)
    if not match:
        raise ValueError('missing private run identity')
    listing = subprocess.check_output(['ps', '-axo', 'pid=,ppid=,command='], text=True)
    children = [line.split(maxsplit=2) for line in listing.splitlines()
                if len(line.split(maxsplit=2)) == 3 and line.split(maxsplit=2)[1] == str(controller.pid)]
    if (len(children) != 1 or not children[0][2].startswith(str(binary) + ' ') or
            match[1] + '/pr13-32g.qcow2' not in children[0][2] or '-display none' not in children[0][2]):
        raise ValueError('not exactly the private headless QEMU child')
    command = ['/usr/sbin/taskpolicy', '-b', '-p', children[0][0]]
    result = subprocess.run(command, capture_output=True, text=True, timeout=5)
    if result.returncode:
        raise RuntimeError('private background-policy request failed: ' + result.stderr)
    return dict(command=command, verified_qemu_command=children[0][2],
                stdout=result.stdout, stderr=result.stderr, returncode=result.returncode,
                scope='private QEMU process only; no parent/controller or existing instance policy change')


def validate_result(status, application):
    if (status != 2 or not application['functional_checks_passed'] or
            application['host_graphics_clean'] or application['passed'] or
            application['qemu_exit'] != 0 or not application['measurements']['post_idle_sync']):
        raise ValueError('unexpected outcome: inspect retained evidence, do not accept a fast failure')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-root', type=Path, required=True)
    parser.add_argument('--thread-helper', type=Path)
    parser.add_argument('--cases', nargs='+', choices=CASES,
                        default=['baseline', 'timer-only', 'refresh-33ms', 'headless'])
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[2]
    binary = args.build_root.resolve() / 'qemu-system-arm'
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    out = Path(tempfile.mkdtemp(prefix='scanout-matrix.', dir=repo / 'extracted/qemu-arm64-port'))
    records = []
    print(f'Scanout matrix: {out}', flush=True)
    for index, label in enumerate(args.cases):
        interval, timer_only, mode = CASES[label]
        changes = dict(HARMATTAN_UI_BUILD_ROOT=str(binary.parent), HARMATTAN_UI_IDLE='wfi',
                       HARMATTAN_UI_PROFILE='1', HARMATTAN_UI_SCANOUT_PROBE='1',
                       N00_SCANOUT_REFRESH_MS=interval, N00_SCANOUT_TIMER_ONLY=timer_only)
        if args.thread_helper:
            changes['HARMATTAN_UI_THREAD_HELPER'] = str(args.thread_helper.resolve())
        if label in ('activity-off', 'activity-on'):
            changes.update(HARMATTAN_UI_ACTIVITY_PROBE='1', N00_COCOA_ACTIVITY=str(int(label == 'activity-on')))
        if label in ('interaction-off', 'interaction-on'):
            changes.update(HARMATTAN_UI_ACTIVITY_PROBE='1', N00_COCOA_ACTIVITY='0',
                           HARMATTAN_UI_INTERACTION_PROBE='1',
                           N00_COCOA_INTERACTION=str(int(label == 'interaction-on')))
        env = {key: value for key, value in os.environ.items() if key not in
               ('HARMATTAN_UI_THREAD_HELPER', 'HARMATTAN_UI_ACTIVITY_PROBE', 'N00_COCOA_ACTIVITY',
                'HARMATTAN_UI_INTERACTION_PROBE', 'N00_COCOA_INTERACTION')}
        env.update(changes)
        command = ['sh', str(repo / 'scripts/harmattan-qemu/run-arm64-ui.sh'), mode]
        log_path = out / f'{index:02d}-{label}.log'
        record = dict(label=label, environment=changes, command=command, qemu_sha256=digest,
                      runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                      log=str(log_path), started_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
        records.append(record)
        started = time.monotonic()
        child = None
        print(f'BEGIN {index} {label}; log: {log_path}', flush=True)
        try:
            with log_path.open('x') as log:
                child = subprocess.Popen(command, cwd=repo, env=env, stdout=log,
                                         stderr=subprocess.STDOUT, start_new_session=True)
                record['controller_pid'] = child.pid
                if label == 'headless-background':
                    record['background_policy'] = background_private_child(child, log_path, binary)
                record['controller_exit'] = child.wait(timeout=480)
        finally:
            # Only the new, private session created above can be interrupted.
            # Never select QEMU processes globally or touch existing instances.
            if child is not None and child.poll() is None:
                os.killpg(child.pid, signal.SIGINT)
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait(timeout=5)
            record['wall_seconds'] = time.monotonic() - started
            output = log_path.read_text()
            match = re.search(r'^Native UI run artifacts: (.+)$', output, re.MULTILINE)
            record['run_directory'] = match[1] if match else None
            (out / 'matrix.json').write_text(json.dumps(records, indent=2) + '\n')
        print(output, end='', flush=True)
        if not match:
            raise RuntimeError('missing run directory')
        application = json.loads((Path(match[1]) / 'ui/application-result.json').read_text())
        validate_result(record['controller_exit'], application)
        if application['qemu_sha256'] != digest or hashlib.sha256(binary.read_bytes()).hexdigest() != digest:
            raise ValueError('diagnostic binary changed')
        print(f'END {label}: functional pass; graphics remains partial', flush=True)
    print(f'Matrix complete: {out}', flush=True)


if __name__ == '__main__':
    main()
