#!/usr/bin/env python3
"""Verify SSI MMIO, INTC wiring and GDD RAM transfers; no guest firmware or modem."""
import argparse
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import time

SPEC = importlib.util.spec_from_file_location(
    "display_smoke", Path(__file__).with_name("smoke-arm64-display.py"))
display = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(display)
BASE = 0x48058000
INTC_INPUTS2 = 0x482000c0


def exercise(command, mode, output):
    env = display.qemu_environment() | {
        "HARMATTAN_N00_SSI": "off" if mode == "disabled" else "on",
        "HARMATTAN_N00_SDK_POWER": "off",
    }
    args = command + (["-global", "n00-ssi.loopback=on"] if mode == "loopback" else [])
    # A short temporary socket path also supports deeply nested output paths.
    with tempfile.TemporaryDirectory(prefix="n00-ssi-") as temporary, socket.socket(socket.AF_UNIX) as server:
        # The board requires a kernel input. Supply our own ARM B-to-self word;
        # qtest does not execute it. Keep the normal boot-input check intact.
        fixture = Path(temporary) / "arm-loop.bin"
        fixture.write_bytes(bytes.fromhex("feffffea"))
        address = str(Path(temporary) / "qtest")
        server.bind(address)
        server.listen(1)
        server.settimeout(10)
        with (output / f"{mode}-stderr.log").open("xb") as errors:
            process = subprocess.Popen(args + ["-kernel", str(fixture), "-qtest", "unix:" + address,
                "-qtest-log", str(output / f"{mode}-qtest.log"), "-qmp", "stdio"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors,
                env=env, bufsize=0)
            try:
                qmp = display.QMP(process, time.monotonic() + 45)
                connection, _ = server.accept()
                with connection, connection.makefile("rb") as replies:
                    connection.settimeout(10)

                    def call(request):
                        connection.sendall(request.encode() + b"\n")
                        reply = replies.readline().decode().strip()
                        if not (reply == "OK" or reply.startswith("OK ")):
                            raise RuntimeError(f"qtest command failed: {request}: {reply}")
                        return reply[2:].strip()

                    # Original cold loaders read the SCM strap before choosing
                    # GP or HS monitor calls. Check byte lanes, not only a word.
                    if int(call("readl 0x480022f0"), 0) != 0x30f:
                        raise ValueError("Nokia GP CONTROL_STATUS is missing")
                    for address, value in ((0x480022f0, 0x0f), (0x480022f1, 3),
                                           (0x480022f2, 0), (0x480022f3, 0)):
                        if int(call(f"readb {address:#x}"), 0) != value:
                            raise ValueError("CONTROL_STATUS byte order mismatch")

                    def put(offset, value, size=4):
                        call(f"write{'l' if size == 4 else 'w'} {BASE + offset:#x} {value:#x}")

                    def get(offset, size=4):
                        return int(call(f"read{'l' if size == 4 else 'w'} {BASE + offset:#x}"), 0)

                    def check(condition, message):
                        if not condition:
                            raise ValueError(f"{mode}: {message}")

                    if mode == "disabled":
                        check(get(0) == 0 and get(0x14) == 0, "SSI unexpectedly enabled")
                    else:
                        check(get(0) == 0x10 and get(0x14) == 1, "identity/reset")
                        put(0x2004, 2)
                        put(0x2804, 2)
                        put(0x80c, 1)
                        check(int(call(f"readl {INTC_INPUTS2:#x}"), 0) & 8, "IRQ67 not asserted")
                        put(0x2080, 0x1234abcd)
                        if mode == "disconnected":
                            check(get(0x2010) == 1 and get(0x2810) == 0, "nonexistent peer accepted data")
                            check(not (int(call(f"readl {INTC_INPUTS2:#x}"), 0) & 8), "IRQ67 stayed asserted")
                        else:
                            check(get(0x2880) == 0x1234abcd, "PIO roundtrip")
                            put(0x80c, 0)
                            put(0x814, 0x100)
                            put(0x2080, 0x51ef98a3)
                            check(int(call(f"readl {INTC_INPUTS2:#x}"), 0) & 16, "IRQ68 not asserted")
                            check(get(0x2880) == 0x51ef98a3, "second PIO frame")
                            check(not (int(call(f"readl {INTC_INPUTS2:#x}"), 0) & 16), "IRQ68 not cleared")
                            put(0x814, 0)
                            words = [0xa5000031 ^ (i * 0x1a312f) for i in range(32)]
                            for i, word in enumerate(words):
                                call(f"writel {0x80001000 + 4 * i:#x} {word:#x}")
                                call(f"writel {0x80002000 + 4 * i:#x} 0")

                            def dma(ch, rx, count, address):
                                b = 0x1800 + ch * 0x40
                                put(b, 0x9026 if rx else 0x1322, 2)
                                put(b + 4, 0x21, 2)
                                put(b + 8, BASE + 0x2880 if rx else address)
                                put(b + 12, address if rx else BASE + 0x2080)
                                put(b + 16, count, 2)
                                put(b + 2, 0x1090 if rx else 0x1081, 2)

                            put(0x804, 3)
                            dma(0, True, len(words), 0x80002000)
                            check(get(0x1802, 2) & 0x80, "empty RX completed")
                            dma(1, False, len(words), 0x80001000)
                            actual = [int(call(f"readl {0x80002000 + 4 * i:#x}"), 0) for i in range(len(words))]
                            check(actual == words, "GDD RAM roundtrip mismatch")
                            check(get(0x800) == 3, "GDD channel completion")
                            check(int(call(f"readl {INTC_INPUTS2:#x}"), 0) & 128, "IRQ71 not asserted")
                            put(0x800, 3)
                            check(not (int(call(f"readl {INTC_INPUTS2:#x}"), 0) & 128), "IRQ71 not cleared")
                            check(get(0x1806, 2) == 0x20 and get(0x1846, 2) == 0x20, "GDD completion status")
                            dma(0, False, 2, 0x48004000)
                            check(get(0x1806, 2) == 1, "DMA to MMIO was not rejected")
                        put(0x10, 2)
                        check(get(0x2010) == 0 and get(0x2810) == 0 and get(0x804) == 0, "reset leaked pending state")
                    # Keep qtest connected until QEMU tears it down. Closing
                    # first triggers two CLOSED callbacks in QEMU 9.1's logger.
                    qmp.deadline = time.monotonic() + 10
                    qmp.call("quit")
                    if process.wait(timeout=10) != 0:
                        raise RuntimeError("QEMU exit failed")
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
        host = (output / f"{mode}-stderr.log").read_text().strip()
        if host != "N00_GLES summary calls=0 swaps=0 faults=0 workers=joined":
            raise ValueError("unexpected host diagnostic: " + host)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qemu", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.qemu.is_file():
        parser.error("QEMU binary missing")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    command = [str(args.qemu.resolve()), "-M", "n00-port-spike", "-accel", "qtest",
               "-display", "none", "-nic", "none", "-serial", "none", "-monitor", "none"]
    result = {"status": "FAIL", "scope": "SSI controller only; explicit test loopback",
              "full_services": False, "command": command, "cases": {}}
    try:
        for mode in ("disabled", "disconnected", "loopback"):
            exercise(command, mode, output)
            result["cases"][mode] = "PASS"
        result["status"] = "PASS"
    finally:
        (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(f"PASS: SSI MMIO, PIO, GDD and INTC; no cellular-service acceptance. {output}")


if __name__ == "__main__":
    main()
