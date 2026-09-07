#!/usr/bin/env python3
"""Execute the restricted GP cache monitor's real ARM exception path.

No firmware, disk, network or credentials are used. An ARM-capable clang and
llvm-objcopy are required. The maintained ROM bytes must match its assembly.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "display_smoke", Path(__file__).with_name("smoke-arm64-display.py"))
display = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(display)
BASE = 0x40200000
CASES = {
    "cache-invalidate": (1, 0, 0x600001d3, False, True),
    "conditional-cache-invalidate": (1, 0, 0x600001d3, False, True),
    "cache-other-flags": (1, 0, 0xa00001d3, False, True),
    "repeated-cache-invalidate": (1, 0, 0x900001d3, False, True),
    "hs-smc": (1, 1, 0x600001d3, False, False),
    "unsupported-zero": (0, 0, 0x600001d3, False, False),
    "unsupported-l2acr": (2, 0, 0x600001d3, False, False),
    "unsupported-hs-cache": (0x28, 0, 0x600001d3, False, False),
    "system-mode": (1, 0, 0x600001df, False, False),
    "big-endian": (1, 0, 0x600003d3, False, False),
    "thumb": (1, 0, 0x600001d3, True, False),
}


def compile_asm(source, destination, clang, objcopy):
    obj = destination.with_suffix(".o")
    subprocess.run([clang, "--target=armv7-none-eabi", "-c", str(source),
                    "-o", str(obj)], check=True, capture_output=True)
    subprocess.run([objcopy, "-O", "binary", "--only-section=.text", str(obj),
                    str(destination)], check=True, capture_output=True)


def fixture(name):
    service, immediate, psr, thumb, _ = CASES[name]
    lines = [".syntax unified", ".arch armv7-a", ".arch_extension sec", ".arm",
             ".text", f"movw r0, #{psr & 0xffff}", f"movt r0, #{psr >> 16}",
             "msr cpsr_fsxc, r0"]
    registers = {i: 0x12340000 + i * 0x101 + 0x56 for i in range(15)}
    registers[12] = service
    for index, value in registers.items():
        lines += [f"movw r{index}, #{value & 0xffff}",
                  f"movt r{index}, #{value >> 16}"]
    if thumb:
        lines += ["adr r0, thumb_entry + 1", "bx r0", ".thumb", "thumb_entry:"]
    condition = "eq" if name.startswith("conditional-") else ""
    lines += [f"smc{condition} #{immediate}"]
    if name == "repeated-cache-invalidate":
        lines += ["smc #0"]
    lines += ["b finished", ".balign 4",
              ".arm", ".org 0x200", "finished: b finished"]
    return "\n".join(lines) + "\n", registers


def parse_registers(text):
    registers = {int(n): int(v, 16) for n, v in
                 re.findall(r"\bR(\d{2})=([0-9a-fA-F]{8})\b", text)}
    psr = re.search(r"\bPSR=([0-9a-fA-F]{8})\b", text)
    if len(registers) != 16 or psr is None:
        raise ValueError("Incomplete QEMU ARM register snapshot")
    return registers, int(psr.group(1), 16)


def validate(name, snapshot, expected):
    registers, psr = parse_registers(snapshot)
    if CASES[name][-1]:
        if registers[15] != BASE + 0x200 or psr != CASES[name][2]:
            raise ValueError(f"{name}: exception return PC/CPSR mismatch")
        if any(registers[i] != value for i, value in expected.items()):
            raise ValueError(f"{name}: caller register was changed")
    elif registers[15] != 0x80 or psr & 0x1f != 0x16:
        raise ValueError(f"{name}: unsupported call did not stop in Monitor mode")


def exercise(qemu, name, binary, output):
    command = [str(qemu), "-M", "n00-port-spike", "-kernel", str(binary),
               "-device", f"loader,file={binary},addr={BASE:#x},cpu-num=0,force-raw=on",
               "-display", "none", "-nic", "none", "-serial", "none", "-monitor", "none",
               "-qmp", "stdio", "-S"]
    environment = display.qemu_environment() | {
        "HARMATTAN_N00_GP_CACHE_MONITOR": "on",
        "HARMATTAN_N00_SDK_POWER": "off", "HARMATTAN_N00_SSI": "off"}
    with (output / f"{name}-stderr.log").open("xb") as errors:
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=errors, env=environment, bufsize=0)
        try:
            qmp = display.QMP(process, time.monotonic() + 15)
            qmp.call("cont")
            time.sleep(0.1)
            qmp.call("stop")
            snapshot = qmp.call("human-monitor-command", {"command-line": "info registers"})
            qmp.call("quit")
            process.wait(timeout=5)
            if process.returncode:
                raise ValueError(f"{name}: QEMU exited {process.returncode}")
            return snapshot
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qemu", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--clang", default=os.environ.get("HARMATTAN_ARMEL_CLANG") or
                        shutil.which("clang"))
    parser.add_argument("--objcopy", default=None)
    args = parser.parse_args()
    if not args.clang:
        parser.error("ARM-capable clang is required")
    objcopy = args.objcopy or str(Path(args.clang).resolve().with_name("llvm-objcopy"))
    args.output.mkdir(parents=True, exist_ok=False)
    output = args.output.resolve()
    rom = output / "monitor.bin"
    compile_asm(ROOT / "ports/qemu-n00/n00-gp-cache-monitor.S", rom, args.clang, objcopy)
    header = (ROOT / "ports/qemu-n00/n00-gp-cache-monitor.h").read_text()
    if rom.read_bytes() != bytes(int(x, 16) for x in re.findall(r"0x([0-9a-f]{2})\b", header)):
        raise ValueError("Maintained ROM bytes differ from assembled source")
    results = {}
    for name in CASES:
        source, expected = fixture(name)
        assembly = output / f"{name}.S"
        assembly.write_text(source)
        binary = assembly.with_suffix(".bin")
        compile_asm(assembly, binary, args.clang, objcopy)
        snapshot = exercise(args.qemu.resolve(), name, binary, output)
        (output / f"{name}-registers.txt").write_text(snapshot)
        validate(name, snapshot, expected)
        results[name] = "PASS"
    report = {"status": "PASS", "scope": "GP cache API 1 only; no secure-boot acceptance",
              "rom_sha256": hashlib.sha256(rom.read_bytes()).hexdigest(), "cases": results}
    (output / "result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
