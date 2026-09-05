#!/usr/bin/env python3
"""Exercise the original guest libEGL/libGLESv2 inside a real Xorg window."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import socket
import subprocess
import time

SPEC = importlib.util.spec_from_file_location("display_smoke", Path(__file__).with_name("smoke-arm64-display.py"))
display = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(display)
XORG_SPEC = importlib.util.spec_from_file_location("xorg_smoke", Path(__file__).with_name("smoke-arm64-xorg.py"))
xorg = importlib.util.module_from_spec(XORG_SPEC)
XORG_SPEC.loader.exec_module(xorg)
LIBRARIES = {
    "/usr/lib/libEGL.so.1": "2d33b733564f1adf8d2978f6e74efde2",
    "/usr/lib/libGLESv2.so.1": "061a075a2191fd79abd43640851c60b2",
    "/usr/lib/libX11.so.6": "9b9136ffeecd7bdd756a1911eb6b5169",
    "/lib/libc.so.6": "4fa0cc0a22c03b0b14b9c5848c6a4267",
}
MARKERS = (
    b"N00_PUBLIC_EGL version=1.4 vendor=Nokia Corporation",
    b"N00_PUBLIC_GL renderer=FGLES2 QEMU Accelerator. version=2.0 FGLES2",
    b"N00_PUBLIC_FRAME_0_OK pixels=829440",
    b"N00_PUBLIC_FRAME_1_OK pixels=829440",
    b"N00_PUBLIC_TERMINATE result=0 error=3008",
    b"N00_PUBLIC_GUEST_OK", b"N00_PUBLIC_EXIT_0", b"N00_PUBLIC_XORG_STOPPED_0",
)


def checkpoint(data, marker):
    lines = data.replace(b"\r", b"").split(b"\n")[:-1]
    if any(line.startswith(b"N00_PUBLIC_FAIL:") or
           (line.startswith(b"N00_PUBLIC_EXIT_") and line != b"N00_PUBLIC_EXIT_0") or
           (line.startswith(b"N00_PUBLIC_XORG_STOPPED_") and line != b"N00_PUBLIC_XORG_STOPPED_0") for line in lines):
        raise ValueError("original-library guest test failed; inspect serial.log")
    return marker in lines


def validate_serial(data, noxshm, shell_api=False):
    data = data.replace(b"\r", b"")
    lines = data.split(b"\n")[:-1]
    required = MARKERS + (f"N00_PUBLIC_START noxshm={noxshm}".encode(),)
    if shell_api:
        required += (b"N00_SHELL_API_OK pixels=30 rejects=2",)
    elif b"N00_SHELL_API_OK" in data:
        raise ValueError("shell API probe requires its own verification profile")
    if not all(lines.count(marker) == 1 for marker in required):
        raise ValueError("missing single complete public API checkpoints")
    checkpoint(data, b"N00_PUBLIC_EXIT_0")
    if b"Fatal server error" in data or b"X Error of failed request" in data:
        raise ValueError("Xorg/Xlib failure")
    blocks = re.findall(rb"\nN00_PUBLIC_MAPS_BEGIN\n(.*?)\nN00_PUBLIC_MAPS_END\n", data, re.DOTALL)
    if len(blocks) != 1:
        raise ValueError("missing single process mapping snapshot")
    for library in (b"/usr/lib/libEGL.so.1.3.0", b"/usr/lib/libGLESv2.so.1.4.9",
                    b"/usr/lib/libX11.so.6.3.0", b"/lib/libc-2.10.1.so"):
        if not re.search(rb"^[0-9a-f]+-[0-9a-f]+ r-xp .* " + re.escape(library) + rb"$", blocks[0], re.MULTILINE):
            raise ValueError("original guest library not mapped executable")
    segments = re.findall(rb"^([0-9a-f]+)-([0-9a-f]+) rw-s .* /SYSV[^\n]*$", blocks[0], re.MULTILINE)
    sizes = [int(end, 16) - int(start, 16) for start, end in segments]
    if sizes != ([] if noxshm == "1" else [864 * 480 * 4]):
        raise ValueError("actual shared memory mappings do not match exchange mode")
    for library, digest in LIBRARIES.items():
        matches = re.findall(rb"([0-9a-f]{32})  " + re.escape(library.encode()) + rb"\n", data)
        if matches != [digest.encode()]:
            raise ValueError("runtime guest library identity mismatch")
    for marker in (b"X.Org X Server 1.9.5", b"Virtual size is 864x480", b"framebuffer bpp 32",
                   b"Loading /usr/lib/xorg/modules/drivers/omapfb_drv.so"):
        if marker not in data:
            raise ValueError("missing original Xorg display evidence")
    errors = re.findall(rb"^(?:\[\s*\d+\.\d+\]\s+)?\(EE\) ([^\n]+)", data, re.MULTILINE)
    if any(error not in xorg.INPUT_ERRORS for error in errors):
        raise ValueError("unexpected Xorg errors")
    return {"runtime_library_md5": LIBRARIES, "sysv_mapping_bytes": sizes,
            "known_input_errors": sorted(set(error.decode() for error in errors)),
            "known_guest_library_defect": "eglTerminate repeats with NULL: EGL_FALSE / EGL_BAD_DISPLAY"}


def validate_host(data, shell_api=False):
    lines = data.strip().split(b"\n")
    calls, compiles, links, uploads, draws, rejects = (177, 4, 2, 3, 11, 2) if shell_api else (69, 2, 1, 2, 2, 0)
    expected = [b"N00_GLES connect client=0 abi=1", b"N00_GLES connect client=1 abi=2", None,
                b"N00_GLES terminate client=1 released=1 backend=retained",
                b"N00_GLES terminate client=1 rejected=bad-display",
                b"N00_GLES disconnect client=1", b"N00_GLES disconnect client=0",
                f"N00_GLES render compiles={compiles} links={links} uploads={uploads} draws={draws} rejects={rejects}".encode(),
                f"N00_GLES summary calls={calls} swaps=2 faults=0 workers=joined".encode()]
    if len(lines) != len(expected):
        raise ValueError("unexpected host log shape")
    for actual, wanted in zip(lines, expected):
        if wanted is not None and actual != wanted:
            raise ValueError("unexpected call counts, termination or worker exit")
    if not re.fullmatch(rb"N00_GLES current client=1 es=2 renderer=Apple [^\n]+", lines[2]):
        raise ValueError("missing actual Apple GPU renderer")
    result = {"calls": calls, "swaps": 2, "faults": 0, "workers_joined": True,
              "compiles": compiles, "links": links, "uploads": uploads, "draws": draws}
    if shell_api:
        result["expected_parameter_rejections"] = rejects
    return result


def verify_frame(data, frame):
    header = b"P6\n864 480\n255\n"
    top = bytes((0, 0, 255)) * 432 + bytes((255, 255, 255)) * 432
    bottom = bytes((255, 0, 255 if frame else 0)) * 432 + bytes((0, 255, 0)) * 432
    pixels = top * 240 + bottom * 240
    if not data.startswith(header) or data[len(header):] != pixels:
        raise ValueError(f"public API frame {frame} did not reach DSS unchanged")
    return hashlib.sha256(pixels).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--probe", required=True, type=Path)
    parser.add_argument("--noxshm", choices=("0", "1"), default="0")
    parser.add_argument("--shell-api", action="store_true", help="also require RGB565 and shell GL state pixel checks")
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command or "-snapshot" not in command or args.timeout <= 0:
        parser.error("QEMU command must include -snapshot and a positive timeout")
    probe = args.probe.read_bytes()
    if (not probe.startswith(b"\x7fELF\x01\x01") or probe[16:20] != b"\x02\0\x28\0" or
            len(probe) > 1024 * 1024 or not int.from_bytes(probe[36:40], "little") & 0x400):
        parser.error("expected small non-PIE hard-float ARM ELF32 executable")
    if b"/lib/ld-linux.so.3\0" not in probe:
        parser.error("expected original guest dynamic loader, not a static MMIO probe")
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
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
                display.wait_serial(serial, process, log, lambda data: checkpoint(data, marker), deadline)

            def upload(data, path, delimiter):
                encoded = data.hex()
                serial.sendall(f"/usr/bin/perl -ne 'chomp; print pack(\"H*\",$_)' > {path} <<'{delimiter}'\n".encode())
                for start in range(0, len(encoded), 76):
                    serial.sendall(encoded[start:start+76].encode() + b"\n")
                serial.sendall(f"{delimiter}\nprintf '\\n{delimiter}_DONE\\n'\n".encode())
                wait(f"{delimiter}_DONE".encode())

            display.wait_serial(serial, process, log,
                lambda data: b"shell ready" in data and b"/ # " in data, deadline)
            serial.sendall(b"dmesg -n 1; stty -echo; PS2=''; ulimit -l unlimited; /sbin/modprobe kfgles2; printf '\\nN00_PUBLIC_UPLOAD_READY\\n'\n")
            wait(b"N00_PUBLIC_UPLOAD_READY")
            upload(probe, "/tmp/n00-gles-public", "N00_PUBLIC_EOF")
            setup = (
                "export PATH=/sbin:/bin:/usr/sbin:/usr/bin; mkdir -p /tmp/.X11-unix /var/log; "
                "Xorg :9 -config /etc/X11/xorg.conf -noreset >/tmp/n00-public-Xorg.log 2>&1 & n00_xpid=$!; "
                "n00_wait=0; while kill -0 $n00_xpid 2>/dev/null && [ ! -S /tmp/.X11-unix/X9 ] && [ $n00_wait -lt 12 ]; "
                "do sleep 1; n00_wait=$((n00_wait+1)); done; "
                "chmod 700 /tmp/n00-gles-public; "
                "md5sum /usr/lib/libEGL.so.1 /usr/lib/libGLESv2.so.1 /usr/lib/libX11.so.6 /lib/libc.so.6; "
                f"DISPLAY=:9 FGLES2_NOXSHM={args.noxshm} /tmp/n00-gles-public; "
                "rc=$?; printf '\\nN00_PUBLIC_EXIT_%s\\n' $rc\n"
            )
            upload(setup.encode(), "/tmp/n00-public-start", "N00_START_EOF")
            serial.sendall(b". /tmp/n00-public-start\n")
            frame_hashes = []
            for frame in range(2):
                wait(f"N00_PUBLIC_FRAME_{frame}_OK pixels=829440".encode())
                for ext in ("ppm", "png"):
                    qmp.call("screendump", {"filename": str(out / f"public-frame-{frame}.{ext}"), "format": ext})
                frame_hashes.append(verify_frame((out / f"public-frame-{frame}.ppm").read_bytes(), frame))
                serial.sendall(b"c\n")
            wait(b"N00_PUBLIC_EXIT_0")
            serial.sendall(b"cat /tmp/n00-public-Xorg.log; cat /var/log/Xorg.9.log; kill $n00_xpid; wait $n00_xpid; printf '\\nN00_PUBLIC_XORG_STOPPED_%s\\n' $?\n")
            wait(b"N00_PUBLIC_XORG_STOPPED_0")
            qmp.call("quit")
            process.wait(timeout=5)
            if process.returncode != 0:
                raise RuntimeError("QEMU did not exit cleanly")
            guest = validate_serial((out / "serial.log").read_bytes(), args.noxshm, args.shell_api)
            host = validate_host((out / "qemu-stderr.log").read_bytes(), args.shell_api)
            result = {"passed": True, "scope": "original guest libraries + Xorg window rendering; known legacy termination defect; not UI shell/input",
                "command": command, "noxshm": args.noxshm, "frame_rgb_sha256": frame_hashes,
                "guest": guest, "host": host, "guest_rgb_pixels_checked": 1658880,
                "framebuffer_pixels_checked": 829440, "clear_rgb_checks": 2,
                "probe_sha256": hashlib.sha256(probe).hexdigest(),
                "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "qemu_sha256": hashlib.sha256(Path(command[0]).read_bytes()).hexdigest(),
                "total_wall_seconds": round(time.monotonic() - started, 3)}
            if args.shell_api:
                result["shell_api_rgb_checks"] = 30
            (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    finally:
        serial.close(); child.close()
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=5)
            process.stdin.close(); process.stdout.close()
    print(f"PASS: original guest EGL/GLES, two X11 frames, noxshm={args.noxshm}, shell_api={args.shell_api}; evidence: {out}")


if __name__ == "__main__":
    main()
