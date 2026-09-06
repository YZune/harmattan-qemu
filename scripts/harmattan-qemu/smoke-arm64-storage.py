#!/usr/bin/env python3
"""Two persistent guest boots and an independent snapshot isolation check."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import socket
import subprocess
import time


def sibling(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


display = sibling('smoke-arm64-display')
storage = sibling('arm64-storage')


def boot(command, output, script, profile=None):
    output.mkdir()
    serial, child = socket.socketpair()
    process = None
    deadline = time.monotonic() + 120
    try:
        with (output / 'serial.log').open('xb') as log, (output / 'qemu-stderr.log').open('xb') as errors:
            process = subprocess.Popen(command + ['-qmp', 'stdio', '-chardev',
                f'socket,id=n00serial,fd={child.fileno()}', '-serial', 'chardev:n00serial', '-monitor', 'none'],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors, env=display.qemu_environment(),
                pass_fds=(child.fileno(),) + ((profile.fd,) if profile else ()), bufsize=0)
            child.close()
            qmp = display.QMP(process, deadline)
            display.wait_serial(serial, process, log, lambda data: b'shell ready' in data and b'/ # ' in data, deadline)
            serial.sendall(b"dmesg -n 1; stty -echo; PS2=''; printf '\\nN00_STORAGE_SHELL\\n'\n")
            display.wait_serial(serial, process, log, lambda data: display.has_line(data, b'N00_STORAGE_SHELL'), deadline)
            if profile:
                storage.prepare_guest(serial, process, log, display)
            serial.sendall(b"perl -ne 'chomp; print pack(\"H*\",$_)' > /tmp/n00-storage-test.sh <<'N00_STORAGE_SCRIPT'\n")
            payload = script.encode().hex()
            for offset in range(0, len(payload), 76):
                serial.sendall(payload[offset:offset + 76].encode() + b'\n')
            serial.sendall(b"N00_STORAGE_SCRIPT\nsh /tmp/n00-storage-test.sh; printf '\\nN00_STORAGE_TEST_EXIT_%s\\n' $?; printf 'N00_STORAGE_TEST_DONE\\n'\n")
            display.wait_serial(serial, process, log, lambda data: display.has_line(data, b'N00_STORAGE_TEST_DONE'), deadline)
            data = (output / 'serial.log').read_bytes().replace(b'\r', b'')
            if [line for line in data.splitlines() if line.startswith(b'N00_STORAGE_TEST_EXIT_')] != [b'N00_STORAGE_TEST_EXIT_0']:
                raise ValueError('persistent file test failed')
            storage.sync_guest(serial, process, log, display)
            qmp.call('stop')
            qmp.call('quit')
            code = process.wait(timeout=10)
        display.validate_display_host((output / 'qemu-stderr.log').read_bytes(), code)
        if profile:
            profile.finish(synced=True, exit_code=code)
        return data
    finally:
        serial.close()
        child.close()
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            process.stdin.close()
            process.stdout.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--image-tool', type=Path, required=True)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ['--'] else args.command
    output = args.output.resolve()
    profile_path = output / 'profile'
    storage.persistent_command(command, profile_path / 'disk.qcow2')
    output.mkdir(parents=True, exist_ok=False)
    nonce = os.urandom(12).hex()
    value = os.urandom(1024)
    digest = hashlib.md5(value).hexdigest()
    targets = (f'/var/lib/n00-storage-test-{nonce}', f'/home/user/.n00-storage-test-{nonce}')
    before = args.base.stat()
    result = {'passed': False, 'scope': 'system/home file persistence through two clean boots and snapshot isolation; not application data or power-loss acceptance',
              'bytes_per_file': len(value), 'md5': digest, 'qemu_sha256': hashlib.sha256(Path(command[0]).read_bytes()).hexdigest()}
    try:
        for phase in ('write', 'read'):
            profile = storage.Profile(profile_path, args.base, args.image_tool)
            try:
                script = 'set -eu\nprintf \"\\n\"\n'
                for target in targets:
                    if phase == 'write':
                        script += f"perl -e 'print pack(\"H*\",\"{value.hex()}\")' > {shlex.quote(target)}\n"
                    script += f'md5sum {shlex.quote(target)}\n'
                data = boot(storage.persistent_command(command, profile.disk), output / phase, script, profile)
                for target in targets:
                    if data.splitlines().count(f'{digest}  {target}'.encode()) != 1:
                        raise ValueError('file did not retain identical bytes across boots')
                result[phase] = {'passed': True, 'profile_state': profile.state['state']}
            finally:
                profile.close()
            print(f'PASS: persistent system and home files, {phase}.', flush=True)
        boot(command, output / 'snapshot', 'set -eu\n' + ''.join(f'test ! -e {target}\n' for target in targets))
        after = args.base.stat()
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError('source raw clone metadata changed')
        result.update(passed=True, snapshot_isolated=True, source_raw_metadata_unchanged=True)
        print('PASS: profile survives restart; independent snapshot sees neither file.', flush=True)
    except Exception as exc:
        result['error'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        (output / 'storage-result.json').write_text(json.dumps(result, indent=2) + '\n')


if __name__ == '__main__':
    main()
