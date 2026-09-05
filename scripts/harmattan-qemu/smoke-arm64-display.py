#!/usr/bin/env python3
"""Verify guest-written pixels through native N00 DSS, not an UI benchmark."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import select
import socket
import subprocess
import time


WIDTH, HEIGHT = 864, 480
FATAL = (b"Kernel panic", b"Internal error: Oops", b"Blocked re-entrant IO",
         b"Spurious DMA IRQ", b"dpll4_ck failed transition",
         b"can't get VDDS_DSI regulator")
PERL = (
    'for($y=0;$y<480;$y++){$row="";for($x=0;$x<864;$x++){'
    'if($y<320){$v=int($x/108);'
    '$r=($v==0||$v==1||$v==4||$v==5)?255:0;$g=($v<4)?255:0;'
    '$b=($v==0||$v==2||$v==4||$v==6)?255:0}'
    'else{$r=int(255*$x/863);$g=int(255*($y-320)/159);'
    '$b=((int($x/32)+int($y/32))%2)*255}'
    'INVERT'
    '$row.=pack("C4",$b,$g,$r,0)}print $row}'
)


def frame_command(number):
    invert = "" if number == 1 else "$r=255-$r;$g=255-$g;$b=255-$b;"
    code = PERL.replace("INVERT", invert)
    # Perl pack is required: this rootfs' BusyBox awk drops NUL bytes.
    return (f"/usr/bin/perl -e '{code}' > /dev/fb0 && sync && "
            f"printf '\\nN00_FRAME_{number}_READY\\n'\n").encode()


def expected_rgb(inverted=False):
    data = bytearray()
    for y in range(HEIGHT):
        for x in range(WIDTH):
            if y < 320:
                band = x // 108
                rgb = (255 if band in (0, 1, 4, 5) else 0,
                       255 if band < 4 else 0,
                       255 if band in (0, 2, 4, 6) else 0)
            else:
                rgb = (255 * x // 863, 255 * (y - 320) // 159,
                       ((x // 32 + y // 32) % 2) * 255)
            data.extend(255 - v if inverted else v for v in rgb)
    return bytes(data)


def surface_point(x, y, rotation=0, width=WIDTH, height=HEIGHT):
    """Raw framebuffer -> QEMU presentation. -rotate uses CCW degrees."""
    if rotation == 0:
        return x, y
    if rotation == 90:
        return y, width - 1 - x
    if rotation == 180:
        return width - 1 - x, height - 1 - y
    if rotation == 270:
        return height - 1 - y, x
    raise ValueError('rotation must be 0, 90, 180 or 270')


def native_ppm(data, rotation=0, width=WIDTH, height=HEIGHT):
    """Normalize bytes for assertions only; never rewrite captured images."""
    surface_point(0, 0, rotation, width, height)  # validate rotation
    out_width, out_height = (height, width) if rotation in (90, 270) else (width, height)
    header = f'P6\n{out_width} {out_height}\n255\n'.encode()
    if not data.startswith(header) or len(data) != len(header) + width * height * 3:
        raise ValueError('unexpected framebuffer dimensions or PPM length')
    if rotation == 0:
        return data
    pixels = memoryview(data)[len(header):]
    raw = bytearray(width * height * 3)
    for y in range(height):
        for x in range(width):
            dx, dy = surface_point(x, y, rotation, width, height)
            offset = (dy * out_width + dx) * 3
            index = (y * width + x) * 3
            raw[index:index + 3] = pixels[offset:offset + 3]
    return f'P6\n{width} {height}\n255\n'.encode() + raw


def verify_ppm(data, inverted=False, rotation=0):
    if rotation:
        data = native_ppm(data, rotation)
    # QEMU's own P6 writer uses this header (no comments or padding).
    header = f"P6\n{WIDTH} {HEIGHT}\n255\n".encode()
    if not data.startswith(header):
        raise ValueError("unexpected framebuffer dimensions or PPM format")
    pixels = data[len(header):]
    expected = expected_rgb(inverted)
    if pixels != expected:
        if len(pixels) != len(expected):
            raise ValueError(f"pixel length {len(pixels)} != {len(expected)}")
        offset = next(i for i, (a, b) in enumerate(zip(pixels, expected)) if a != b)
        pixel = offset // 3
        raise ValueError(f"pixel mismatch at ({pixel % WIDTH},{pixel // WIDTH}), "
                         f"channel {offset % 3}: {pixels[offset]} != {expected[offset]}")
    return hashlib.sha256(pixels).hexdigest()


class QMP:
    def __init__(self, process, deadline):
        self.process = process
        self.deadline = deadline
        self.buffer = b""
        self.sequence = 0
        if "QMP" not in self.receive():
            raise RuntimeError("missing QMP greeting")
        self.call("qmp_capabilities")

    def receive(self):
        while b"\n" not in self.buffer:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0 or not select.select(
                    [self.process.stdout], [], [], remaining)[0]:
                raise TimeoutError("QMP timed out")
            chunk = os.read(self.process.stdout.fileno(), 65536)
            if not chunk:
                raise RuntimeError("QEMU closed QMP")
            self.buffer += chunk
        line, self.buffer = self.buffer.split(b"\n", 1)
        return json.loads(line)

    def call(self, name, arguments=None):
        self.sequence += 1
        message = {"execute": name, "id": self.sequence}
        if arguments is not None:
            message["arguments"] = arguments
        self.process.stdin.write(json.dumps(message).encode() + b"\n")
        self.process.stdin.flush()
        while True:
            reply = self.receive()
            if reply.get("id") == self.sequence:
                if "error" in reply:
                    raise RuntimeError(f"QMP {name}: {reply['error']}")
                return reply.get("return")


def qemu_environment():
    # macOS can strip DYLD_* while traversing a Python version-manager shell
    # shim. Reconstruct the child-only path from the launcher's build manifest.
    env = os.environ.copy()
    runtime = env.get('HARMATTAN_DGLES_RUNTIME_DIR')
    if runtime:
        env['DYLD_LIBRARY_PATH'] = runtime
    return env


def wait_serial(serial, process, log, predicate, deadline):
    tail = b""
    while time.monotonic() < deadline:
        if not select.select([serial], [], [], 0.2)[0]:
            if process.poll() is not None:
                raise RuntimeError(f"QEMU exited: {process.returncode}")
            continue
        data = serial.recv(65536)
        if not data:
            raise RuntimeError("serial connection closed")
        log.write(data)
        log.flush()
        tail = (tail + data)[-131072:]
        if any(marker in tail for marker in FATAL):
            raise RuntimeError("kernel/display/DMA failure; inspect serial.log")
        clean = tail.replace(b"\r", b"")
        if predicate(clean):
            return
    raise TimeoutError("serial checkpoint timed out")


def has_line(data, line):
    return line in data.split(b"\n")


def validate_display_host(data, exit_code):
    if exit_code != 0 or data not in (b'', b'N00_GLES summary calls=0 swaps=0 faults=0 workers=joined\n'):
        raise ValueError('unexpected host error or graphics activity in framebuffer-only test')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--rotation", type=int, choices=(0, 90, 180, 270), default=0)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command or "-snapshot" not in command or args.timeout <= 0:
        parser.error("a positive timeout and QEMU command with -snapshot are required")
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    names = ["serial.log", "qemu-stderr.log", "display-result.json"]
    names += [f"frame-{n}.{ext}" for n in (1, 2) for ext in ("ppm", "png")]
    if any((out / name).exists() for name in names):
        parser.error("output evidence exists; choose a fresh directory")
    started = time.monotonic()
    deadline = started + args.timeout
    results = {"width": WIDTH, "height": HEIGHT, "bpp": 32, "stride": WIDTH * 4,
               "scope": "guest Perl -> /dev/fb0 -> DSS -> QMP; no Xorg/GLES/input",
               "frames": []}
    results['rotation'] = args.rotation
    results['command'] = command
    results['qemu_sha256'] = hashlib.sha256(Path(command[0]).read_bytes()).hexdigest()
    results['runner_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    serial, child_serial = socket.socketpair()
    process = None
    try:
        with (out / "serial.log").open("xb") as log, (
                out / "qemu-stderr.log").open("xb") as error_log:
            process = subprocess.Popen(
                command + ["-qmp", "stdio", "-chardev",
                           f"socket,id=n00serial,fd={child_serial.fileno()}",
                           "-serial", "chardev:n00serial", "-monitor", "none"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=error_log,
                env=qemu_environment(),
                pass_fds=(child_serial.fileno(),), bufsize=0)
            child_serial.close()
            qmp = QMP(process, deadline)
            wait_serial(serial, process, log,
                        lambda data: b"shell ready" in data and b"/ # " in data,
                        deadline)
            results["shell_wall_seconds"] = round(time.monotonic() - started, 3)
            print("Guest shell ready; checking framebuffer metadata.", flush=True)
            probe = (
                "dmesg -n 1; "
                "test -c /dev/fb0 && test -x /usr/bin/perl && "
                "test \"$(cat /sys/class/graphics/fb0/virtual_size)\" = 864,480 && "
                "test \"$(cat /sys/class/graphics/fb0/bits_per_pixel)\" = 32 && "
                "test \"$(cat /sys/class/graphics/fb0/stride)\" = 3456 && "
                "cat /proc/fb && "
                "printf '\\nN00_FB_METADATA_OK\\n'\n"
            )
            serial.sendall(probe.encode())
            wait_serial(serial, process, log,
                        lambda data: has_line(data, b"N00_FB_METADATA_OK"), deadline)
            for number in (1, 2):
                serial.sendall(frame_command(number))
                wait_serial(
                    serial, process, log,
                    lambda data: has_line(data, f"N00_FRAME_{number}_READY".encode()),
                    deadline)
                for ext in ("ppm", "png"):
                    qmp.call("screendump", {"filename": str(out / f"frame-{number}.{ext}"),
                                           "format": ext})
                digest = verify_ppm((out / f"frame-{number}.ppm").read_bytes(),
                                    inverted=number == 2, rotation=args.rotation)
                results["frames"].append({"number": number, "rgb_sha256": digest,
                                          "pixels_matched": WIDTH * HEIGHT})
                print(f"Frame {number}: all {WIDTH * HEIGHT} pixels match.", flush=True)
            serial.sendall(b"sync && printf '\\nN00_DISPLAY_FINAL_IO_OK\\n'\n")
            wait_serial(serial, process, log,
                        lambda data: has_line(data, b"N00_DISPLAY_FINAL_IO_OK"), deadline)
            qmp.call('quit')
            process.wait(timeout=5)
            validate_display_host((out / 'qemu-stderr.log').read_bytes(), process.returncode)
            results['qemu_exit'] = process.returncode
            results['host_clean'] = True
            results["passed"] = True
            results["total_wall_seconds"] = round(time.monotonic() - started, 3)
            with (out / "display-result.json").open("x") as result_file:
                json.dump(results, result_file, ensure_ascii=False, indent=2)
                result_file.write("\n")
    finally:
        serial.close()
        child_serial.close()
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
    print(f"PASS: native framebuffer, two exact frames; evidence: {out}", flush=True)


if __name__ == "__main__":
    main()
