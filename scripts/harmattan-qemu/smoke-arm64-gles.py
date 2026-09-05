#!/usr/bin/env python3
"""Run an ARMEL guest GLES protocol probe in a disposable native QEMU."""
import argparse
import hashlib
import importlib.util
import json
import re
import socket
import subprocess
import time
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "display_smoke", Path(__file__).with_name("smoke-arm64-display.py"))
display = importlib.util.module_from_spec(spec)
spec.loader.exec_module(display)

MARKERS = (
    b"N00_GLES_ES1_KFGLES2_OK pixels=829440",
    b"N00_GLES_ES2_KFGLES2_OK pixels=829440",
    b"N00_GLES_ES2_SOFTFP_DIRECT_OK pixels=829440",
    b"N00_GLES_GUEST_OK",
    b"N00_PROBE_EXIT_0",
)
RENDER_MARKERS = (
    b"N00_GLES_RENDER_SHADER_LOG_OK",
    b"N00_GLES_RENDER_CLIENT_OK pixels=829440",
    b"N00_GLES_RENDER_VBO_EBO_OK pixels=829440",
    b"N00_GLES_RENDER_RGB_ALIGNMENT_OK pixels=829440",
    b"N00_GLES_RENDER_INDEX8_TINT_OK pixels=829440",
    b"N00_GLES_RENDER_PACK_ALIGNMENT_OK",
    b"N00_GLES_RENDER_GUEST_OK",
    b"N00_PROBE_EXIT_0",
)


def probe_complete(data):
    lines = data.replace(b"\r", b"").split(b"\n")[:-1]
    if any(line.startswith(b"N00_GLES_FAIL:") or
           (line.startswith(b"N00_PROBE_EXIT_") and line != b"N00_PROBE_EXIT_0")
           for line in lines):
        raise ValueError("guest probe failed; inspect serial.log")
    return b"N00_PROBE_EXIT_0" in lines


def validate_serial(data, negative=False, render=False):
    lines = data.replace(b"\r", b"").split(b"\n")[:-1]
    required = RENDER_MARKERS if render else MARKERS
    if negative:
        required += (b"N00_GLES_RENDER_NEGATIVE_OK rejections=7" if render else b"N00_GLES_NEGATIVE_OK",)
    if b"N00_GLES_FAIL:" in data or b"N00_PROBE_EXIT_1" in data:
        raise ValueError("guest probe failed")
    if not all(lines.count(marker) == 1 for marker in required):
        raise ValueError("missing complete guest pass markers")


def validate_host(data, negative=False, render=False):
    if b"unsupported/invalid" in data or b"ERROR" in data or b"failed" in data:
        raise ValueError("unexpected host GLES error")
    summaries = re.findall(rb"N00_GLES summary calls=(\d+) swaps=(\d+) faults=(\d+) workers=joined", data)
    if len(summaries) != 1:
        raise ValueError("missing single completed worker summary")
    calls, swaps, faults = map(int, summaries[0])
    expected_calls = (122 if negative else 104) if render else (126 if negative else 120)
    expected_swaps = 4 if render else 6
    expected_faults = (1 if render else 3) if negative else 0
    if calls != expected_calls or swaps != expected_swaps or faults != expected_faults:
        raise ValueError("unexpected GLES call/swap/fault count")
    expected_rejections = [
        b"N00_GLES rejected guest memory client=1 api=0 call=6",
        b"N00_GLES invalid MMIO offset=0x400",
        b"N00_GLES invalid MMIO offset=0x3f004",
    ] if negative else []
    if render and negative:
        expected_rejections = [b"N00_GLES rejected guest memory client=1 api=2 call=98"]
    rejected = re.findall(rb"N00_GLES (?:rejected|invalid)[^\n]*", data)
    if rejected != expected_rejections:
        raise ValueError("unexpected rejected calls")
    if not data.rstrip().endswith(b"workers=joined"):
        raise ValueError("host log continued after the completed worker summary")
    if len(re.findall(rb"N00_GLES current client=\d+ es=[12] renderer=Apple", data)) != (1 if render else 3):
        raise ValueError("missing actual Apple renderer evidence")
    abis = re.findall(rb"N00_GLES connect client=\d+ abi=(\d+)", data)
    expected_abis = [b"2"] if render else ([b"1"] if negative else []) + [b"2", b"2", b"1"]
    if abis != expected_abis:
        raise ValueError("unexpected kernel/direct floating-point ABI selection")
    result = {"calls": calls, "swaps": swaps, "expected_faults": faults, "workers_joined": True}
    stats = re.findall(rb"N00_GLES render compiles=(\d+) links=(\d+) uploads=(\d+) draws=(\d+) rejects=(\d+)", data)
    if render:
        expected = (3, 1, 3, 4, 6 if negative else 0)
        if len(stats) != 1 or tuple(map(int, stats[0])) != expected:
            raise ValueError("unexpected shader/texture/draw/rejection counts")
        result["render"] = dict(zip(("compiles", "links", "uploads", "draws", "rejections"), expected))
    elif stats:
        raise ValueError("render calls in clear-only regression")
    return result


def verify_frame(data, render=False):
    header = b"P6\n864 480\n255\n"
    if not data.startswith(header):
        raise ValueError("unexpected framebuffer format or dimensions")
    pixels = data[len(header):]
    expected = bytearray()
    for y in range(480):
        for x in range(864):
            if render:
                column = 0 if x < 288 else 1 if x < 576 else 2
                colors = ((0, 0, 255), (0, 0, 255), (255, 0, 255)) if y < 240 else ((255, 0, 0), (0, 0, 0), (255, 0, 0))
                expected.extend(colors[column])
            elif x < 432 and y >= 240:
                expected.extend((0, 255, 0))
            elif x >= 432 and y < 240:
                expected.extend((0, 0, 255))
            else:
                expected.extend((0, 255, 255))
    if pixels != expected:
        raise ValueError("GLES-to-DSS framebuffer pixel mismatch")
    return hashlib.sha256(pixels).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--probe", required=True, type=Path)
    parser.add_argument("--negative", action="store_true")
    parser.add_argument("--render", action="store_true", help="shader, texture and vertex transport probe")
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command or "-snapshot" not in command or args.timeout <= 0:
        parser.error("QEMU command must include -snapshot and a positive timeout")
    probe = args.probe.read_bytes()
    if not probe.startswith(b"\x7fELF\x01\x01") or len(probe) > 1024 * 1024:
        parser.error("expected a small ELF32 little-endian ARM probe")
    if probe[18:20] != b"\x28\x00":
        parser.error("probe must target ARM, not AArch64 or the host")
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    deadline = started + args.timeout
    serial, child = socket.socketpair()
    process = None
    try:
        with (out / "serial.log").open("xb") as log, (
                out / "qemu-stderr.log").open("xb") as errors:
            process = subprocess.Popen(command + ["-qmp", "stdio", "-chardev",
                f"socket,id=n00serial,fd={child.fileno()}", "-serial",
                "chardev:n00serial", "-monitor", "none"], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=errors, pass_fds=(child.fileno(),),
                bufsize=0)
            child.close()
            qmp = display.QMP(process, deadline)
            def wait_line(marker):
                display.wait_serial(serial, process, log,
                    lambda data: display.has_line(data, marker.encode()), deadline)
            display.wait_serial(serial, process, log,
                lambda data: b"shell ready" in data and b"/ # " in data, deadline)
            serial.sendall(b"dmesg -n 1; stty -echo; PS2=''; "
                b"/sbin/modprobe kfgles2; ls -l /dev/kfgles2; "
                b"printf '\\nN00_UPLOAD_READY\\n'\n")
            wait_line("N00_UPLOAD_READY")
            # Short lines respect BusyBox's canonical TTY buffer. Upload only
            # into this run's -snapshot; no host mount or rootfs mutation.
            encoded = probe.hex()
            serial.sendall(b"/usr/bin/perl -ne 'chomp; print pack(\"H*\",$_)' "
                b"> /tmp/n00-gles-probe <<'N00_PROBE_EOF'\n")
            for index in range(0, len(encoded), 76):
                serial.sendall(encoded[index:index+76].encode() + b"\n")
            serial.sendall(b"N00_PROBE_EOF\nchmod 700 /tmp/n00-gles-probe\n"
                b"/tmp/n00-gles-probe; rc=$?; printf '\\nN00_PROBE_EXIT_%s\\n' \"$rc\"\n")
            display.wait_serial(serial, process, log, probe_complete, deadline)
            validate_serial((out / "serial.log").read_bytes(), args.negative, args.render)
            for ext in ("ppm", "png"):
                qmp.call("screendump", {"filename": str(out / f"gles-frame.{ext}"), "format": ext})
            frame_sha = verify_frame((out / "gles-frame.ppm").read_bytes(), args.render)
            qmp.call("quit")
            process.wait(timeout=5)
            if process.returncode != 0:
                raise RuntimeError("QEMU did not exit cleanly")
            host = validate_host((out / "qemu-stderr.log").read_bytes(), args.negative, args.render)
            result = {"passed": True, "scope": "ARMEL wire probe, not Xorg or application compatibility",
                "command": command, "host": host, "render": args.render,
                "guest_rgb_pixels_checked": 3317760 if args.render else 4976640,
                "framebuffer_pixels_checked": 414720, "frame_rgb_sha256": frame_sha,
                "probe_sha256": hashlib.sha256(probe).hexdigest(),
                "qemu_sha256": hashlib.sha256(Path(command[0]).read_bytes()).hexdigest(),
                "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
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
    profile = "GLES2 shader/texture/vertices, four frames" if args.render else "GLES1/2, six frames"
    print(f"PASS: ARMEL {profile} and DSS; evidence: {out}")


if __name__ == "__main__":
    main()
