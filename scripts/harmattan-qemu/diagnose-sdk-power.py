#!/usr/bin/env python3
"""Run original BME against SDK power devices on a disposable raw-image snapshot."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import socket
import subprocess
import time

SPEC = importlib.util.spec_from_file_location(
    "display_smoke", Path(__file__).with_name("smoke-arm64-display.py"))
display = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(display)

# Original DFL61 SDK Nolo command line, not a retail N9 partition layout.
PARTITIONS = ("mtdparts=omap2-onenand:128k(bootloader),384k@128k(config),"
              "3072k@512k(kernel),1024k@3584k(log),519680k@4608k(swap)")


def validate_kernel_log(data):
    # A rescue shell can appear after SLUB has repaired poisoned objects.
    # Such a run must never pass merely because later IPC checkpoints succeed.
    if re.search(rb"(?:^|\n)(?:<\d+>)?(?:\[\s*[0-9.]+\]\s*)?"
                 rb"(?:BUG[: ]|kernel BUG at|Unable to handle kernel|"
                 rb"Internal error:|Kernel panic)", data.replace(b"\r", b"")):
        raise ValueError("guest kernel fault or allocator corruption")


def validate_serial(data):
    data = data.replace(b"\r", b"")
    lines = data.splitlines()
    for marker in (b"N00_BME_IDENTITY_OK", b"N00_BME_ABSENT_REJECTED",
                   b"N00_BME_STATS_BEGIN", b"N00_BME_STATS_END",
                   b"N00_BME_ALIVE", b"N00_BME_STOPPED", b"N00_BME_EXIT_0"):
        if lines.count(marker) != 1:
            raise ValueError("missing or ambiguous original BME checkpoint")
    records = re.findall(rb"^N00_BME_STATS_BEGIN\n(.*?)\nN00_BME_STATS_END$",
                         data, re.M | re.S)
    if len(records) != 1:
        raise ValueError("missing or ambiguous BME statistics")
    values = {}
    for key in ("max. level", "cur. level", "pct. level"):
        found = re.findall(rb"^\s*battery " + re.escape(key.encode()) + rb":\s*(\d+)\s*$",
                           records[0], re.M)
        if len(found) != 1:
            raise ValueError("missing or ambiguous battery level")
        values[key] = int(found[0])
    if not (0 <= values["cur. level"] <= values["max. level"] > 0
            and 0 <= values["pct. level"] <= 100):
        raise ValueError("invalid BME battery level")
    return values


def run_diagnostic(*, description=__doc__, guest_script="sdk-power-guest.sh",
                   prefix="N00_BME", probe_flag="n00.sdk_power_probe=1",
                   validator=validate_serial, result_key="battery",
                   scope="original BME hardware and IPC only"):
    """Shared bounded transport; guest validators own the acceptance criteria."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--qemu", required=True, type=Path)
    parser.add_argument("--kernel", required=True, type=Path)
    parser.add_argument("--image", required=True, type=Path, help="quiescent prepared raw disk")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timeout", type=int, default=150)
    args = parser.parse_args()
    if not 30 <= args.timeout <= 600:
        parser.error("timeout must be between 30 and 600 seconds")
    for path in (args.qemu, args.kernel, args.image):
        if not path.is_file():
            parser.error(f"missing input: {path}")
    # QEMU's legacy -drive syntax treats commas specially.
    if "," in str(args.image.resolve()):
        parser.error("raw image path must not contain commas")
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    command = [str(args.qemu.resolve()), "-M", "n00-port-spike", "-no-reboot",
               "-kernel", str(args.kernel.resolve()), "-display", "none", "-nic", "none",
               "-drive", f"if=sd,format=raw,file={args.image.resolve()}", "-snapshot",
               "-append", "init=/sbin/preinit root=0xB302 rootfstype=ext4 rw rootdelay=2 "
               "console=ttyS0,115200n8 omap3_die_id " + probe_flag + " " + PARTITIONS]
    serial, child = socket.socketpair()
    deadline = time.monotonic() + args.timeout
    environment = display.qemu_environment() | {"HARMATTAN_N00_SDK_POWER": "on"}
    result = {"scope": scope, "full_services": False,
              "command": command, "status": "FAIL",
              "hardware": {"sdk_power": "on", "ssi": environment.get("HARMATTAN_N00_SSI", "off")}}
    process = None
    try:
        with (out / "serial.log").open("xb") as log, (out / "qemu-stderr.log").open("xb") as errors:
            process = subprocess.Popen(command + ["-qmp", "stdio", "-chardev",
                f"socket,id=serial,fd={child.fileno()}", "-serial", "chardev:serial", "-monitor", "none"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors,
                pass_fds=(child.fileno(),), env=environment, bufsize=0)
            child.close()
            qmp = display.QMP(process, deadline)

            def wait(marker):
                display.wait_serial(serial, process, log, lambda data: marker in data, deadline)

            wait(b"/ # ")
            serial.sendall(b"dmesg -n 1; stty -echo; PS2=''; printf '0\\n' > "
                           b"/sys/devices/platform/serial8250.2/sleep_timeout; "
                           b"printf '\\nN00_UPLOAD_READY\\n'\n")
            wait(b"\nN00_UPLOAD_READY\n")
            payload = Path(__file__).with_name(guest_script).read_bytes().hex()
            serial.sendall(b"perl -ne 'chomp; print pack(\"H*\",$_)' > /tmp/n00-sdk-power.sh <<'PAYLOAD'\n")
            for pos in range(0, len(payload), 76):
                serial.sendall(payload[pos:pos + 76].encode() + b"\n")
            serial.sendall(b"PAYLOAD\nsh /tmp/n00-sdk-power.sh; " +
                           f"printf '\\n{prefix}_EXIT_%s\\n{prefix}_DONE\\n' $?\n".encode())
            wait(f"\n{prefix}_DONE\n".encode())
            evidence = (out / "serial.log").read_bytes()
            validate_kernel_log(evidence)
            result[result_key] = validator(evidence)
            qmp.deadline = time.monotonic() + 10
            qmp.call("quit")
            if process.wait(timeout=10) != 0:
                raise RuntimeError("QEMU exit failed")
        host = (out / "qemu-stderr.log").read_text()
        if host.strip() != "N00_GLES summary calls=0 swaps=0 faults=0 workers=joined":
            raise ValueError("unexpected host diagnostic or incomplete teardown")
        result["status"] = "PASS"
    except Exception as error:
        result["error"] = str(error)
        raise
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        serial.close()
        child.close()
        (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    return result, out


def main():
    _, out = run_diagnostic()
    print(f"PASS: original BME hardware/IPC; complete power and cellular services remain unverified. {out}")


if __name__ == "__main__":
    main()
