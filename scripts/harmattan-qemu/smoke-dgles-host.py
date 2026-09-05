#!/usr/bin/env python3
"""Run native Nokia DGLES host tests; no QEMU, guest, Xorg, or UI coverage."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import tempfile
import time


COMMON_MARKERS = (
    "CLEAR_FRAME_1_OK pixels=3072",
    "CLEAR_FRAME_2_OK pixels=3072",
    "TRIANGLE_OK center=green corner=blue",
    "ORIENTATION_AND_PACK_STATE_OK pixels=3072",
    "CLIENT_GL_ERROR_PRESERVED_OK",
    "UNSUPPORTED_SURFACE_GUARDS_OK",
    "RESIZE_OK pixels=2961",
)


def validate_result(api, returncode, stdout, stderr):
    if api not in (1, 2):
        raise ValueError("GLES API must be 1 or 2")
    if returncode != 0 or stderr:
        raise ValueError(f"GLES{api} failed: exit={returncode}, stderr={stderr!r}")
    lines = stdout.splitlines()
    final = f"HARMATTAN_DGLES{api}_HOST_SMOKE_OK"
    required = list(COMMON_MARKERS) + [final, "GLES_WORKER_JOIN_OK"]
    if api == 2:
        required.append("USER_FBO_SWITCH_OK")
    if not lines or lines[-1] != "GLES_WORKER_JOIN_OK":
        raise ValueError("missing terminal success marker")
    for marker in required:
        if lines.count(marker) != 1:
            raise ValueError(f"missing/duplicate exact checkpoint: {marker}")
    for prefix in ("GL_VENDOR=", "GL_RENDERER=", "GL_VERSION="):
        values = [line[len(prefix):] for line in lines if line.startswith(prefix)]
        if len(values) != 1 or not values[0]:
            raise ValueError(f"missing graphics identity: {prefix}")
    if any("FAIL:" in line for line in lines):
        raise ValueError("failure mixed with success output")


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    repo = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path,
                        default=repo / "extracted/qemu-arm64-port/dgles2-host")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--expect-legacy-pbuffer-failure", action="store_true",
                        help="also require CGL invalid drawable in FBO=0 control")
    args = parser.parse_args()
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        parser.error("run from native arm64 macOS, not Rosetta")
    if args.runs not in range(1, 11) or not 0 < args.timeout <= 60:
        parser.error("runs must be 1..10 and timeout must be >0 and <=60 seconds")
    work = args.workspace.resolve()
    source = work / "gles-libs-1.4.2/dgles2"
    libraries = source / "objs-arm64"
    artifacts = [work / f"smoke-dgles{api}-host" for api in (1, 2)]
    artifacts += [libraries / name for name in (
        "libEGL.1.4.2.dylib", "libGLES_CM.1.4.1.dylib", "libGLESv2.2.0.0.dylib")]
    for artifact in artifacts:
        if not artifact.is_file():
            parser.error(f"missing native artifact: {artifact}; run build-dgles2-host.sh")
        identity = subprocess.check_output(["file", str(artifact)], text=True)
        if "Mach-O 64-bit" not in identity or "arm64" not in identity or "x86_64" in identity:
            parser.error(f"not a native arm64 artifact: {identity}")
    if args.output is not None:
        out = args.output.resolve()
        if out.exists():
            parser.error("output exists; choose a fresh evidence directory")
        out.mkdir(parents=True)
    else:
        out = Path(tempfile.mkdtemp(prefix="host-run.", dir=work))
    environment = os.environ.copy()
    environment.pop("DYLD_INSERT_LIBRARIES", None)
    environment["DYLD_LIBRARY_PATH"] = str(libraries)
    environment["DGLES2_COCOA_FBO"] = "1"
    results = {
        "scope": "native host EGL/DGLES1/DGLES2 -> CGL FBO -> BGRA CPU readback; no QEMU/guest/UI",
        "passed": False,
        "host": subprocess.check_output(["sw_vers"], text=True).splitlines(),
        "architecture": platform.machine(),
        "workspace": str(work),
        "artifacts_sha256": {str(path.relative_to(work)): sha256(path) for path in artifacts},
        "patch_sha256": sha256(repo / "ports/dgles2/gles-libs-1.4.2-cocoa-fbo.patch"),
        "test_source_sha256": sha256(repo / "scripts/harmattan-qemu/smoke-dgles2-host.c"),
        "config": (source / "config-arm64.mak").read_text(),
        "runs": [],
    }
    failure = None
    try:
        cases = [(api, number, False) for number in range(1, args.runs + 1) for api in (1, 2)]
        if args.expect_legacy_pbuffer_failure:
            cases.append((2, 0, True))
        for api, number, negative in cases:
            label = "legacy-pbuffer-control" if negative else f"gles{api}-run-{number}"
            environment["DGLES2_COCOA_FBO"] = "0" if negative else "1"
            started = time.monotonic()
            with (out / f"{label}.stdout.log").open("xb") as stdout_log, (
                    out / f"{label}.stderr.log").open("xb") as stderr_log:
                # subprocess.run kills/reaps only its own child on timeout.
                completed = subprocess.run([str(work / f"smoke-dgles{api}-host")],
                                           env=environment, stdout=stdout_log,
                                           stderr=stderr_log, timeout=args.timeout)
            stdout = (out / f"{label}.stdout.log").read_text()
            stderr = (out / f"{label}.stderr.log").read_text()
            result = {"label": label, "api": api, "returncode": completed.returncode,
                      "wall_seconds": round(time.monotonic() - started, 3),
                      "negative_control": negative, "passed": False}
            results["runs"].append(result)
            if negative:
                if (completed.returncode != 1 or stdout or
                        "DGLES2 CGLCreatePBuffer: 10005 invalid drawable" not in stderr or
                        "FAIL: create Nokia offscreen surface (EGL=0x3003)" not in stderr):
                    raise ValueError("control did not reproduce the expected CGL PBuffer failure")
            else:
                validate_result(api, completed.returncode, stdout, stderr)
            result["passed"] = True
            print(f"PASS {label} ({result['wall_seconds']}s)", flush=True)
        results["passed"] = True
    except (OSError, subprocess.TimeoutExpired, ValueError) as error:
        failure = str(error)
        results["error"] = failure
    finally:
        with (out / "host-result.json").open("x") as result_file:
            json.dump(results, result_file, ensure_ascii=False, indent=2)
            result_file.write("\n")
    print(f"Host-only evidence: {out}", flush=True)
    if failure:
        raise SystemExit(f"FAIL: {failure}")


if __name__ == "__main__":
    main()
