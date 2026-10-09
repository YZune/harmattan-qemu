#!/usr/bin/env python3
"""Check Linux QEMU worker cleanup ordering; no firmware, guest OS or Mesa context."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import queue
import re
import subprocess
import threading
import time


MARKER = "QEMU_MAIN_RETURN_BEFORE_ATEXIT"
# ARM: mov r0,#1; ldr r1,[pc,#4]; str r0,[r1]; b .; .word 0x4f000000.
# Connect one N00 GLES worker with ABI 1, then remain in a bounded code loop.
FIXTURE = bytes.fromhex("0100a0e304109fe5000081e5feffffea0000004f")


def validate_cleanup(mode, returncode, stderr):
    if mode not in ("prelaunch", "running", "paused"):
        raise ValueError("unknown VM state")
    if returncode != 0:
        raise ValueError(f"QEMU exited with {returncode}")
    lines = stderr.splitlines()
    summaries = [line for line in lines if line.startswith("N00_GLES summary ")]
    if len(summaries) != 1 or not re.fullmatch(
            r"N00_GLES summary calls=0 swaps=0 faults=0 workers=joined", summaries[0]):
        raise ValueError("missing/duplicate or unexpected graphics summary")
    if lines.count(MARKER) != 1 or lines.index(summaries[0]) > lines.index(MARKER):
        raise ValueError("graphics cleanup did not finish before libc atexit")
    connects = [line for line in lines if line.startswith("N00_GLES connect ")]
    disconnects = [line for line in lines if line.startswith("N00_GLES disconnect ")]
    expected = 0 if mode == "prelaunch" else 1
    if len(connects) != expected or len(disconnects) != expected:
        raise ValueError("unexpected worker connect/disconnect count")
    if expected and (connects != ["N00_GLES connect client=1 abi=1"] or
                     disconnects != ["N00_GLES disconnect client=1"] or
                     not lines.index(connects[0]) < lines.index(disconnects[0]) <
                     lines.index(summaries[0])):
        raise ValueError("worker was not joined before the graphics summary")
    unexpected = set(lines) - set(connects + disconnects + summaries + [MARKER])
    if unexpected:
        raise ValueError(f"unexpected QEMU stderr: {sorted(unexpected)!r}")
    return {"summaries": 1, "workers_joined": expected,
            "cleanup_before_main_return": True, "no_duplicate_atexit_summary": True}


class QMP:
    def __init__(self, process, log):
        self.process = process
        self.responses = queue.Queue()
        self.sequence = 0

        def read():
            try:
                for line in process.stdout:
                    log.write(line)
                    log.flush()
                    self.responses.put(json.loads(line))
            except (OSError, ValueError) as error:
                self.responses.put(error)
            finally:
                self.responses.put(EOFError("QMP closed"))

        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()
        greeting = self.receive()
        if "QMP" not in greeting:
            raise ValueError("missing QMP greeting")
        self.command("qmp_capabilities")

    def receive(self):
        try:
            response = self.responses.get(timeout=10)
        except queue.Empty as error:
            raise TimeoutError("QMP response timed out") from error
        if isinstance(response, Exception):
            raise response
        return response

    def command(self, execute):
        self.sequence += 1
        self.process.stdin.write(json.dumps({"execute": execute, "id": self.sequence}) + "\n")
        self.process.stdin.flush()
        while True:
            response = self.receive()
            if response.get("id") == self.sequence:
                if "error" in response:
                    raise ValueError(f"QMP {execute}: {response['error']}")
                return response["return"]


def run_case(qemu, fixture, environment, out, mode):
    command = [str(qemu), "-M", "n00-port-spike", "-kernel", str(fixture),
               "-device", f"loader,file={str(fixture).replace(',', ',,')},"
               "addr=0x40200000,cpu-num=0,force-raw=on",
               "-display", "none", "-nic", "none", "-serial", "none",
               "-monitor", "none", "-qmp", "stdio", "-S"]
    stderr_path = out / f"{mode}.stderr.log"
    with stderr_path.open("x") as stderr, (out / f"{mode}.qmp.log").open("x") as qmp_log:
        process = subprocess.Popen(command, env=environment, text=True,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr)
        qmp = None
        try:
            qmp = QMP(process, qmp_log)
            if mode != "prelaunch":
                qmp.command("cont")
                deadline = time.monotonic() + 10
                while "N00_GLES connect client=1 abi=1\n" not in stderr_path.read_text():
                    if process.poll() is not None or time.monotonic() >= deadline:
                        raise TimeoutError("synthetic ARM worker did not connect")
                    time.sleep(0.02)
                if mode == "paused":
                    qmp.command("stop")
            state = qmp.command("query-status")
            if state["status"] != mode or state["running"] != (mode == "running"):
                raise ValueError(f"unexpected VM state: {state}")
            qmp.command("quit")
            returncode = process.wait(timeout=10)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            process.stdin.close()
            if qmp is not None:
                qmp.reader.join(timeout=5)
            process.stdout.close()
    checks = validate_cleanup(mode, returncode, stderr_path.read_text())
    return {"mode": mode, "passed": True, "before_quit": state,
            "qemu_exit": returncode, **checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qemu", type=Path, required=True)
    parser.add_argument("--dgles-runtime", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cc", default=os.environ.get("HARMATTAN_CC", "cc"))
    args = parser.parse_args()
    if (platform.system(), platform.machine(), platform.libc_ver()[0]) != ("Linux", "x86_64", "glibc"):
        parser.error("this process-exit interposer requires Linux x86_64 with glibc")
    qemu, runtime, out = args.qemu.resolve(), args.dgles_runtime.resolve(), args.output.resolve()
    if not qemu.is_file() or not (runtime / "libEGL.so").is_file():
        parser.error("QEMU and built DGLES runtime are required")
    if out.exists():
        parser.error("output exists; choose a fresh evidence directory")
    out.mkdir(parents=True)
    marker_source = Path(__file__).resolve().parent / "tests/qemu-main-return-marker.c"
    marker = out / "main-return-marker.so"
    subprocess.run([args.cc, "-std=c99", "-Wall", "-Wextra", "-Werror", "-O2",
                    "-shared", "-fPIC", str(marker_source), "-ldl", "-o", str(marker)], check=True)
    fixture = out / "connect-worker-loop.arm"
    fixture.write_bytes(FIXTURE)
    environment = os.environ.copy()
    environment["LD_PRELOAD"] = str(marker)
    environment["LD_LIBRARY_PATH"] = str(runtime) + (
        ":" + environment["LD_LIBRARY_PATH"] if environment.get("LD_LIBRARY_PATH") else "")
    results = {"passed": False, "scope": __doc__, "qemu_sha256": hashlib.sha256(qemu.read_bytes()).hexdigest(),
               "fixture_hex": FIXTURE.hex(), "cases": []}
    try:
        for mode in ("prelaunch", "running", "paused"):
            results["cases"].append(run_case(qemu, fixture, environment, out, mode))
            print(f"PASS {mode} cleanup precedes process exit", flush=True)
        results["passed"] = True
    except (OSError, ValueError, EOFError, TimeoutError, subprocess.SubprocessError) as error:
        results["error"] = str(error)
        raise SystemExit(f"FAIL: {error}; evidence: {out}") from error
    finally:
        (out / "result.json").write_text(json.dumps(results, indent=2) + "\n")
    print(f"Source-only lifecycle evidence: {out}")


if __name__ == "__main__":
    main()
