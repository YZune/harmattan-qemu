#!/usr/bin/env python3
"""Bounded serial smoke test for the disposable N00 port, not a benchmark."""

import argparse
import os
from pathlib import Path
import selectors
import subprocess
import time

SYNC_CONFIRMATION = b"sh -c 'sync && printf \"\\nHARMATTAN_NATIVE_SMOKE_SETTLED\\n\"'\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--settle", type=float, default=35)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command or "-snapshot" not in command:
        parser.error("a QEMU command with -snapshot is required")
    if args.timeout <= 0 or args.settle < 0 or args.settle >= args.timeout:
        parser.error("require 0 <= settle < timeout")

    # Exact-line matching prevents an echoed command from passing the test.
    probe = (
        "dmesg -n 1; "
        "uname -m && "
        "dpkg-query -W libc6 && "
        "grep ' / ext4 ' /proc/mounts && "
        "md5sum /bin/busybox && "
        "dpkg-query -W >/dev/null && "
        "port_test=$(mktemp /tmp/n00-smoke.XXXXXX) && "
        "cp /bin/busybox \"$port_test\" && "
        "cmp /bin/busybox \"$port_test\" && sync && "
        "rm \"$port_test\" && sync && "
        "printf '\\nHARMATTAN_NATIVE_SMOKE_OK\\n'\n"
    )
    if os.environ.get('HARMATTAN_UI_IDLE_PROFILE') == 'wfi':
        probe = ("test -f /sys/devices/platform/serial8250.2/sleep_timeout && "
                 "printf '0\\n' > /sys/devices/platform/serial8250.2/sleep_timeout && "
                 "test \"$(cat /sys/devices/platform/serial8250.2/sleep_timeout)\" = 0 && ( "
                 + probe.rstrip() + " )\n")
    start = time.monotonic()
    sent = False
    tail = b""
    passed = False
    passed_at = None
    confirmation_sent = False
    args.log.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    if env.get('HARMATTAN_DGLES_RUNTIME_DIR'):
        env['DYLD_LIBRARY_PATH'] = env['HARMATTAN_DGLES_RUNTIME_DIR']
    with args.log.open("xb") as log:
        process = subprocess.Popen(command, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, bufsize=0, env=env)
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        try:
            while time.monotonic() - start < args.timeout:
                if (passed_at is not None and not confirmation_sent
                        and time.monotonic() - passed_at >= args.settle):
                    process.stdin.write(SYNC_CONFIRMATION)
                    process.stdin.flush()
                    confirmation_sent = True
                events = selector.select(timeout=0.5)
                if not events:
                    if process.poll() is not None:
                        break
                    continue
                chunk = os.read(process.stdout.fileno(), 65536)
                if not chunk:
                    break
                log.write(chunk)
                log.flush()
                tail = (tail + chunk)[-131072:]
                fatal_markers = (b"Kernel panic", b"Internal error: Oops",
                                 b"Blocked re-entrant IO", b"Spurious DMA IRQ")
                if any(marker in tail for marker in fatal_markers):
                    # Keep the rest of the exception stack before stopping our
                    # child; UART output may split the first Oops across reads.
                    drain_until = time.monotonic() + 1
                    while time.monotonic() < drain_until:
                        if not selector.select(timeout=0.1):
                            continue
                        remainder = os.read(process.stdout.fileno(), 65536)
                        if not remainder:
                            break
                        log.write(remainder)
                        log.flush()
                    raise SystemExit(f"FAIL: kernel/DMA/device I/O error; see {args.log}")
                if not sent and b"shell ready" in tail and b"/ # " in tail:
                    print("Serial shell ready; checking PR1.3 userland.", flush=True)
                    process.stdin.write(probe.encode())
                    process.stdin.flush()
                    sent = True
                lines = tail.replace(b"\r", b"").split(b"\n")
                if sent and passed_at is None and b"HARMATTAN_NATIVE_SMOKE_OK" in lines:
                    passed_at = time.monotonic()
                    print("Read/write checks passed; observing delayed I/O errors.", flush=True)
                if confirmation_sent and b"HARMATTAN_NATIVE_SMOKE_SETTLED" in lines:
                    passed = True
                    break
        finally:
            selector.close()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            process.stdin.close()
            process.stdout.close()
    if not passed:
        raise SystemExit(f"FAIL: serial/userland checkpoint not reached; see {args.log}")
    print(f"PASS: serial shell, package reads, copy/compare/sync, {args.settle:g}s "
          f"observation and final sync; log: {args.log}")


if __name__ == "__main__":
    main()
