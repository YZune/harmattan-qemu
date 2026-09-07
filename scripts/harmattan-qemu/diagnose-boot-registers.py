#!/usr/bin/env python3
"""Check UART extended offsets and opt-in GP monitor ROM, without guest firmware."""
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
UART = 0x49020000


def exercise(qemu, output, mode):
    environment = display.qemu_environment() | {
        "HARMATTAN_N00_SDK_POWER": "off", "HARMATTAN_N00_SSI": "off"}
    environment.pop("HARMATTAN_N00_GP_CACHE_MONITOR", None)
    if mode != "default":
        environment["HARMATTAN_N00_GP_CACHE_MONITOR"] = mode
    with tempfile.TemporaryDirectory(prefix="n00-boot-") as temporary, socket.socket(socket.AF_UNIX) as server:
        fixture = Path(temporary) / "loop.bin"
        fixture.write_bytes(bytes.fromhex("feffffea"))
        address = str(Path(temporary) / "qtest")
        server.bind(address)
        server.listen(1)
        server.settimeout(10)
        command = [str(qemu), "-M", "n00-port-spike", "-kernel", str(fixture),
                   "-display", "none", "-nic", "none", "-serial", "none", "-monitor", "none",
                   "-qmp", "stdio", "-S", "-qtest", "unix:" + address,
                   "-qtest-log", str(output / f"{mode}-qtest.log")]
        if mode == "invalid":
            result = subprocess.run(command, capture_output=True, env=environment, timeout=10)
            if result.returncode == 0 or b"must be on or off" not in result.stderr:
                raise ValueError("Invalid monitor setting was not rejected")
            return
        with (output / f"{mode}-stderr.log").open("xb") as errors:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=errors, env=environment, bufsize=0)
            try:
                qmp = display.QMP(process, time.monotonic() + 30)
                connection, _ = server.accept()
                with connection, connection.makefile("rb") as replies:
                    connection.settimeout(10)

                    def call(command):
                        connection.sendall(command.encode() + b"\n")
                        result = replies.readline().decode().strip()
                        if not (result == "OK" or result.startswith("OK ")):
                            raise ValueError(f"{command}: {result}")
                        return result[2:].strip()

                    def read(offset):
                        return int(call(f"readb {UART + offset:#x}"), 0)

                    def write(offset, value):
                        call(f"writeb {UART + offset:#x} {value:#x}")

                    def check(condition, message):
                        if not condition:
                            raise ValueError(f"{mode}: {message}")

                    rom_word = 0xea00001e if mode == "on" else 0
                    check(int(call("readl 0"), 0) == rom_word, "ROM opt-in mapping")
                    if mode == "on":
                        call("writel 0 0")
                        check(int(call("readl 0"), 0) == rom_word, "ROM is writable")
                        qmp.call("system_reset")
                        check(int(call("readl 0"), 0) == rom_word, "ROM reset contents")
                    check(read(0x50) == 0x30 and read(0x58) == 1, "MVR/SYSS offset")
                    # Distinct writable addresses must not alias after translation.
                    for offset, value in ((0x20, 7), (0x24, 0x35), (0x40, 0x59),
                                          (0x48, 0x63), (0x5c, 0x1c), (0x60, 0x37)):
                        write(offset, value)
                        check(read(offset) == value, f"register {offset:#x} roundtrip")
                    check(read(0x20) == 7 and read(0x40) == 0x59, "MDR1/SCR alias")
                    call(f"writew {UART + 0x40:#x} 0x71")
                    check(int(call(f"readw {UART + 0x40:#x}"), 0) == 0x71, "16-bit SCR access")
                    # Keep QEMU's diagnostic 32-to-8-bit fallback on the UART,
                    # never on low physical memory at the relative offset.
                    call(f"writel {UART + 0x40:#x} 0xa1b2c33e")
                    check(int(call(f"readl {UART + 0x40:#x}"), 0) == 0x3e,
                          "32-bit fallback physical address")
                    write(0x50, 0)
                    write(0x58, 0)
                    check(read(0x50) == 0x30 and read(0x58) == 1, "read-only identity/status")
                    write(0x54, 0x1d)
                    check(read(0x54) == 0x1d, "SYSC writable bits")
                    write(0x54, 2)
                    check(read(0x58) == 1 and read(0x54) == 0, "SYSC soft reset")
                    check(read(0x48) == 0 and read(0x5c) == 0x3f and read(0x60) == 0x69,
                          "extended reset state")
                    # The adjacent 16550 transmit/status region still works.
                    check(read(0x14) & 0x60 == 0x60, "16550 transmit status")
                    write(0, ord("U"))
                    check(read(0x14) & 0x60 == 0x60, "16550 transmit completion")
                qmp.call("quit")
                process.wait(timeout=5)
                check(process.returncode == 0, "QEMU exit")
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qemu", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    modes = ("default", "off", "on", "invalid")
    for mode in modes:
        exercise(args.qemu.resolve(), args.output.resolve(), mode)
    result = {"status": "PASS", "monitor_modes": list(modes),
              "uart": "extended offsets, byte/halfword, RO state, soft reset and 16550 TX"}
    (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
