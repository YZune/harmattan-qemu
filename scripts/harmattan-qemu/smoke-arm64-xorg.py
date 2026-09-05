#!/usr/bin/env python3
"""Start the original guest Xorg and verify X11 root drawing, not desktop/input."""
import argparse
import hashlib
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
MARKERS = (
    b"N00_XORG_PROCESS_0",
    b"N00_X11_SETUP_OK version=11.0 size=864x480 depth=24",
    b"N00_X11_ROOT_DRAW_OK rgb=3769a8",
    b"N00_X11_PROBE_EXIT_0",
    b"N00_XORG_CHECK_DONE",
    b"N00_XORG_STOPPED_0",
)
INPUT_ERRORS = (
    b'xf86OpenSerial: Cannot open device /dev/input/qemu-touchscreen',
    b'mtev: cannot open device',
    b'Couldn\'t init device "Atmel mXT Touchscreen"',
    b'Failed to load module "mouse" (module does not exist, 0)',
    b'Failed to load module "kbd" (module does not exist, 0)',
    b"No input driver matching `mouse'",
    b"No input driver matching `kbd'",
)


def validate_serial(data):
    lines = data.replace(b"\r", b"").split(b"\n")
    if not all(lines.count(marker) == 1 for marker in MARKERS):
        raise ValueError("missing single complete Xorg/X11/exit checkpoints")
    if b"Fatal server error" in data or b"X11 draw/fence error" in data:
        raise ValueError("Xorg or X11 failed")
    for evidence in (b"X.Org X Server 1.9.5", b"Loading /usr/lib/xorg/modules/drivers/omapfb_drv.so",
                     b"Virtual size is 864x480", b"framebuffer bpp 32"):
        if evidence not in data:
            raise ValueError("missing original Xorg/omapfb evidence")
    # Match error records, not the header's '(WW) warning, (EE) error' legend.
    errors = re.findall(rb"^(?:\[\s*\d+\.\d+\]\s+)?\(EE\) ([^\r\n]+)", data, re.MULTILINE)
    unexpected = [error for error in errors if error not in INPUT_ERRORS]
    if unexpected:
        raise ValueError(f"unexpected Xorg errors: {unexpected!r}")
    return sorted(set(error.decode() for error in errors))


def verify_frame(data):
    header = b"P6\n864 480\n255\n"
    expected = bytes((0x37, 0x69, 0xa8)) * (864 * 480)
    if not data.startswith(header) or data[len(header):] != expected:
        raise ValueError("X11 root drawing did not reach the DSS framebuffer")
    return hashlib.sha256(expected).hexdigest()


def validate_host(data):
    # The original omapfb X server uses the framebuffer; no GLES is needed yet.
    expected = b"N00_GLES summary calls=0 swaps=0 faults=0 workers=joined"
    if data.strip() != expected:
        raise ValueError("unexpected host output or incomplete worker teardown")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command or "-snapshot" not in command or args.timeout <= 0:
        parser.error("QEMU command must include -snapshot and a positive timeout")
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    probe = Path(__file__).with_name("smoke-x11-root-guest.pl").read_bytes()
    started = time.monotonic()
    deadline = started + args.timeout
    serial, child = socket.socketpair()
    process = None
    try:
        with (out / "serial.log").open("xb") as log, (out / "qemu-stderr.log").open("xb") as errors:
            process = subprocess.Popen(command + ["-qmp", "stdio", "-chardev",
                f"socket,id=n00serial,fd={child.fileno()}", "-serial", "chardev:n00serial", "-monitor", "none"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors, pass_fds=(child.fileno(),), bufsize=0)
            child.close()
            qmp = display.QMP(process, deadline)

            def wait(marker):
                display.wait_serial(serial, process, log,
                    lambda data: (marker + b"\n") in data, deadline)

            def upload(data, path, delimiter):
                encoded = data.hex()
                serial.sendall(f"/usr/bin/perl -ne 'chomp; print pack(\"H*\",$_)' > {path} <<'{delimiter}'\n".encode())
                for start in range(0, len(encoded), 76):
                    serial.sendall(encoded[start:start+76].encode() + b"\n")
                serial.sendall(f"{delimiter}\nprintf '\\n{delimiter}_DONE\\n'\n".encode())
                wait(f"{delimiter}_DONE".encode())

            display.wait_serial(serial, process, log,
                lambda data: b"shell ready" in data and b"/ # " in data, deadline)
            # stty may flush queued input: complete this handshake before uploading.
            serial.sendall(b"dmesg -n 1; stty -echo; PS2=''; printf '\\nN00_XORG_UPLOAD_READY\\n'\n")
            wait(b"N00_XORG_UPLOAD_READY")
            upload(probe, "/tmp/n00-x11-check", "N00_X11_EOF")
            # :9 avoids historical :0 locks. This guest Xorg has no TCP transport:
            # passing -nolisten tcp to it is fatal, not an extra safety measure.
            setup = (
                "export PATH=/sbin:/bin:/usr/sbin:/usr/bin; "
                "mkdir -p /tmp/.X11-unix /var/log; "
                "Xorg :9 -config /etc/X11/xorg.conf -noreset >/tmp/n00-Xorg-9.log 2>&1 & n00_xpid=$!; "
                "n00_wait=0; while kill -0 $n00_xpid 2>/dev/null && [ ! -S /tmp/.X11-unix/X9 ] && [ $n00_wait -lt 12 ]; "
                "do sleep 1; n00_wait=$((n00_wait+1)); done; "
                "kill -0 $n00_xpid 2>/dev/null; printf '\\nN00_XORG_PROCESS_%s\\n' $?; "
                "ls -l /tmp/.X11-unix/X9; "
                "/usr/bin/perl /tmp/n00-x11-check; printf '\\nN00_X11_PROBE_EXIT_%s\\n' $?; "
                "sleep 1; cat /tmp/n00-Xorg-9.log; cat /var/log/Xorg.9.log; "
                "printf '\\nN00_XORG_CHECK_DONE\\n'\n"
            )
            upload(setup.encode(), "/tmp/n00-xorg-check", "N00_SCRIPT_EOF")
            serial.sendall(b". /tmp/n00-xorg-check\n")
            wait(b"N00_XORG_CHECK_DONE")
            for ext in ("ppm", "png"):
                qmp.call("screendump", {"filename": str(out / f"xorg-frame.{ext}"), "format": ext})
            frame_sha = verify_frame((out / "xorg-frame.ppm").read_bytes())
            serial.sendall(b"kill $n00_xpid 2>/dev/null; wait $n00_xpid; printf '\\nN00_XORG_STOPPED_%s\\n' $?\n")
            wait(b"N00_XORG_STOPPED_0")
            warnings = validate_serial((out / "serial.log").read_bytes())
            qmp.call("quit")
            process.wait(timeout=5)
            if process.returncode != 0:
                raise RuntimeError("QEMU did not exit cleanly")
            validate_host((out / "qemu-stderr.log").read_bytes())
            result = {"passed": True, "scope": "original Xorg + X11 root drawing; no input, GLES client or UI shell",
                "command": command, "framebuffer_pixels_checked": 414720, "frame_rgb_sha256": frame_sha,
                "known_input_errors": warnings, "xorg_exit": 0, "qemu_exit": process.returncode,
                "probe_sha256": hashlib.sha256(probe).hexdigest(),
                "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "qemu_sha256": hashlib.sha256(Path(command[0]).read_bytes()).hexdigest(),
                "total_wall_seconds": round(time.monotonic() - started, 3)}
            (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
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
                    process.wait(timeout=5)
            process.stdin.close()
            process.stdout.close()
    print(f"PASS: original Xorg, X11 root drawing and DSS (no input); evidence: {out}")


if __name__ == "__main__":
    main()
