#!/usr/bin/env python3
"""Check the explicit N00 idle compatibility registers with a stopped CPU."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import select
import subprocess
import time

SPEC = importlib.util.spec_from_file_location('display', Path(__file__).with_name('smoke-arm64-display.py'))
display = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(display)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qemu', required=True, type=Path)
    parser.add_argument('--kernel', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    command = [str(args.qemu.resolve()), '-M', 'n00-port-spike', '-kernel', str(args.kernel.resolve()),
               '-S', '-snapshot', '-display', 'none', '-serial', 'none', '-monitor', 'none',
               '-qtest', 'stdio', '-qtest-log', str(out / 'qtest.log')]
    result = {'scope': 'stopped-CPU register semantics, not guest WFI or suspend/resume acceptance',
              'command': command, 'qemu_sha256': hashlib.sha256(args.qemu.read_bytes()).hexdigest(),
              'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'checks': [], 'passed': False}
    with (out / 'qemu-stderr.log').open('xb') as log:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=log, env=display.qemu_environment(), bufsize=0)
        deadline = time.monotonic() + 20
        buffer = b''

        def call(request):
            nonlocal buffer
            process.stdin.write(request.encode() + b'\n')
            process.stdin.flush()
            while b'\n' not in buffer:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not select.select([process.stdout], [], [], remaining)[0]:
                    raise TimeoutError('qtest response timeout')
                chunk = process.stdout.read(4096)
                if not chunk:
                    raise RuntimeError('qtest closed before response')
                buffer += chunk
            line, buffer = buffer.split(b'\n', 1)
            if not line.startswith(b'OK'):
                raise ValueError(f'qtest failure: {line!r}')
            return line.decode().split()[1:]

        def read(address):
            values = call(f'readl 0x{address:x}')
            if len(values) != 1:
                raise ValueError('missing register response')
            return int(values[0], 16)

        def write(address, value, width='l'):
            if call(f'write{width} 0x{address:x} 0x{value:x}'):
                raise ValueError('unexpected write response')

        def check(label, address, expected, mask=0xffffffff):
            actual = read(address)
            result['checks'].append(dict(label=label, address=address, mask=mask,
                                         expected=expected, actual=actual))
            if actual & mask != expected:
                raise ValueError(f'{label}: {actual:#x} & {mask:#x} != {expected:#x}')

        try:
            check('DPLL3 boot frequency tuple', 0x48004d40, 0x08a61940)
            check('DPLL3 boot locked', 0x48004d20, 1, 1)
            control = read(0x48004d00)
            write(0x48004d00, (control & ~7) | 5)
            check('bypass clears lock', 0x48004d20, 0, 1)
            write(0x48004d00, (control & ~7) | 7)
            check('valid multiplier relocks', 0x48004d20, 1, 1)
            write(0x48004d40, 0x08001940)
            check('zero multiplier is not locked', 0x48004d20, 0, 1)
            write(0x48004d40, 0x08a61940)
            check('valid tuple restored', 0x48004d20, 1, 1)
            write(0x48004a10, 0x40, 'b')
            check('SDRC iclk disabled -> idle', 0x48004a20, 2, 2)
            write(0x48004a10, 0x42, 'b')
            check('SDRC iclk enabled -> active', 0x48004a20, 0, 2)
            for domain in (0x900, 0xa00, 0x1000, 0x1300):
                base = 0x48306000 + domain
                for target in (0, 1, 3):
                    write(base + 0xe0, target)
                    check(f'{domain:x} keeps requested state', base + 0xe0, target, 3)
                    check(f'{domain:x} actual state remains ON', base + 0xe4, 3, 3)
                    check(f'{domain:x} previous state remains ON', base + 0xe8, 3, 3)
                status = read(base + 0xe4)
                write(base + 0xe4, 0)
                check(f'{domain:x} PWSTST read-only', base + 0xe4, status)
                write(base + 0xe8, 0, 'b')
                check(f'{domain:x} retained PREPWSTST clear policy', base + 0xe8, status)
            result['passed'] = True
        except Exception as error:
            result['error'] = str(error)
            raise
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=5)
            result['qemu_exit'] = process.returncode
            result['passed'] = result['passed'] and process.returncode == 0
            (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    if not result['passed']:
        raise RuntimeError('register test or QEMU shutdown failed')
    print(f'PASS: {len(result["checks"])} idle register checks; {out}')


if __name__ == '__main__':
    main()
