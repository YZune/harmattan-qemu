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


LINUX_MARKERS = (
    "PARTIAL_NULL_BINDINGS_REJECTED_OK",
    "REPEATED_INVALID_RESIZE_AND_FOREIGN_SWAP_REJECTED_OK",
    "NATIVE_CONTEXT_UNBOUND_OK",
    "PROCESS_EXIT_AFTER_JOIN_OK",
)


def validate_result(api, returncode, stdout, stderr, *, backend="cocoa",
                    cleanup="context-first", renderer=None):
    if backend not in ("cocoa", "osmesa"):
        raise ValueError("unsupported graphics backend")
    if cleanup not in ("context-first", "surface-first", "early-cleanup"):
        raise ValueError("unsupported cleanup test")
    if backend == "cocoa" and cleanup != "context-first":
        raise ValueError("cleanup variants require OSMesa")
    if api not in (1, 2):
        raise ValueError("GLES API must be 1 or 2")
    if returncode != 0 or stderr:
        raise ValueError(f"GLES{api} failed: exit={returncode}, stderr={stderr!r}")
    lines = stdout.splitlines()
    final = f"HARMATTAN_DGLES{api}_HOST_SMOKE_OK"
    required = list(COMMON_MARKERS) + [final, "GLES_WORKER_JOIN_OK"]
    if api == 2:
        required.append("USER_FBO_SWITCH_OK")
    terminal = "GLES_WORKER_JOIN_OK"
    if backend == "osmesa":
        required.extend(LINUX_MARKERS)
        terminal = "PROCESS_EXIT_AFTER_JOIN_OK"
        if cleanup != "context-first":
            required.append("SURFACE_BEFORE_CONTEXT_PROTECTED_PIXEL_LIFETIME_OK")
        if cleanup == "early-cleanup":
            required.append("EARLY_CLEANUP_IDEMPOTENT_OK")
    if not lines or lines[-1] != terminal:
        raise ValueError("missing terminal success marker")
    for marker in required:
        if lines.count(marker) != 1:
            raise ValueError(f"missing/duplicate exact checkpoint: {marker}")
    identity = {}
    for prefix in ("GL_VENDOR=", "GL_RENDERER=", "GL_VERSION="):
        values = [line[len(prefix):] for line in lines if line.startswith(prefix)]
        if len(values) != 1 or not values[0]:
            raise ValueError(f"missing graphics identity: {prefix}")
        identity[prefix[:-1]] = values[0]
    if lines.index(final) > lines.index("GLES_WORKER_JOIN_OK"):
        raise ValueError("worker was reported joined before graphics cleanup")
    if renderer is not None:
        actual = identity["GL_RENDERER"]
        if actual != renderer and not actual.startswith(renderer + " ("):
            raise ValueError(f"unexpected renderer: {actual!r}; expected {renderer}")
    if any("FAIL:" in line for line in lines):
        raise ValueError("failure mixed with success output")
    return identity


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    repo = Path(__file__).resolve().parents[2]
    linux = (platform.system(), platform.machine()) == ("Linux", "x86_64")
    workspace_name = "qemu-linux-port" if linux else "qemu-arm64-port"
    port_work = repo / "extracted" / workspace_name
    if linux:
        port_work = Path(os.environ.get("HARMATTAN_PORT_WORKSPACE", port_work))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path,
                        default=Path(os.environ.get("HARMATTAN_DGLES_WORKSPACE", port_work / "dgles2-host")))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--expect-legacy-pbuffer-failure", action="store_true",
                        help="also require CGL invalid drawable in FBO=0 control")
    parser.add_argument("--renderer", choices=("llvmpipe", "softpipe"), default="llvmpipe",
                        help="Linux OSMesa software renderer (default: llvmpipe)")
    args = parser.parse_args()
    if not linux and (platform.system(), platform.machine()) != ("Darwin", "arm64"):
        parser.error("run from native arm64 macOS or Linux x86_64")
    if linux and args.expect_legacy_pbuffer_failure:
        parser.error("the legacy PBuffer control requires macOS")
    if args.runs not in range(1, 11) or not 0 < args.timeout <= 60:
        parser.error("runs must be 1..10 and timeout must be >0 and <=60 seconds")
    work = args.workspace.resolve()
    source = work / "gles-libs-1.4.2/dgles2"
    arch = "x86_64" if linux else "arm64"
    libraries = source / f"objs-{arch}"
    artifacts = [work / f"smoke-dgles{api}-host" for api in (1, 2)]
    names = ("libEGL.so.1.4.2", "libGLES_CM.so.1.4.1", "libGLESv2.so.2.0.0") if linux else (
        "libEGL.1.4.2.dylib", "libGLES_CM.1.4.1.dylib", "libGLESv2.2.0.0.dylib")
    artifacts += [libraries / name for name in names]
    for artifact in artifacts:
        if not artifact.is_file():
            parser.error(f"missing native artifact: {artifact}; run build-dgles2-host.sh")
        identity = subprocess.check_output(["file", str(artifact)], text=True)
        native = ("ELF 64-bit" in identity and "x86-64" in identity) if linux else (
            "Mach-O 64-bit" in identity and "arm64" in identity and "x86_64" not in identity)
        if not native:
            parser.error(f"not a native {arch} artifact: {identity}")
    if args.output is not None:
        out = args.output.resolve()
        if out.exists():
            parser.error("output exists; choose a fresh evidence directory")
        out.mkdir(parents=True)
    else:
        out = Path(tempfile.mkdtemp(prefix="host-run.", dir=work))
    environment = os.environ.copy()
    environment.pop("DYLD_INSERT_LIBRARIES", None)
    if linux:
        environment.pop("LD_PRELOAD", None)
        environment["LD_LIBRARY_PATH"] = str(libraries) + (
            ":" + environment["LD_LIBRARY_PATH"] if environment.get("LD_LIBRARY_PATH") else "")
        environment.update(LIBGL_ALWAYS_SOFTWARE="1", GALLIUM_DRIVER=args.renderer,
                           LP_NUM_THREADS="2", MESA_SHADER_CACHE_DIR=str(out / "mesa-cache"))
    else:
        environment["DYLD_LIBRARY_PATH"] = str(libraries)
        environment["DGLES2_COCOA_FBO"] = "1"
    backend = "osmesa" if linux else "cocoa"
    patches = [repo / "ports/dgles2/gles-libs-1.4.2-cocoa-fbo.patch"]
    if linux:
        patches.append(repo / "ports/dgles2/gles-libs-1.4.2-linux-osmesa.patch")
    results = {
        "scope": f"native host EGL/DGLES1/DGLES2 -> {backend} -> BGRA CPU readback; no QEMU/guest/UI",
        "backend": backend,
        "passed": False,
        "host": platform.platform() if linux else subprocess.check_output(["sw_vers"], text=True).splitlines(),
        "architecture": platform.machine(),
        "workspace": str(work),
        "artifacts_sha256": {str(path.relative_to(work)): sha256(path) for path in artifacts},
        "patches_sha256": {str(path.relative_to(repo)): sha256(path) for path in patches},
        "test_source_sha256": sha256(repo / "scripts/harmattan-qemu/smoke-dgles2-host.c"),
        "config": (source / f"config-{arch}.mak").read_text(),
        "runs": [],
    }
    failure = None
    try:
        cleanups = ("context-first", "surface-first", "early-cleanup") if linux else ("context-first",)
        cases = [(api, number, False, cleanup) for number in range(1, args.runs + 1)
                 for api in (1, 2) for cleanup in cleanups]
        if args.expect_legacy_pbuffer_failure:
            cases.append((2, 0, True, "context-first"))
        for api, number, negative, cleanup in cases:
            label = "legacy-pbuffer-control" if negative else f"gles{api}-run-{number}"
            if linux:
                label += f"-{cleanup}"
            command = [str(work / f"smoke-dgles{api}-host")]
            if cleanup != "context-first":
                command.append(f"--{cleanup}")
            environment["DGLES2_COCOA_FBO"] = "0" if negative else "1"
            started = time.monotonic()
            with (out / f"{label}.stdout.log").open("xb") as stdout_log, (
                    out / f"{label}.stderr.log").open("xb") as stderr_log:
                # subprocess.run kills/reaps only its own child on timeout.
                completed = subprocess.run(command,
                                           env=environment, stdout=stdout_log,
                                           stderr=stderr_log, timeout=args.timeout)
            stdout = (out / f"{label}.stdout.log").read_text()
            stderr = (out / f"{label}.stderr.log").read_text()
            result = {"label": label, "api": api, "returncode": completed.returncode,
                      "wall_seconds": round(time.monotonic() - started, 3),
                      "negative_control": negative, "cleanup": cleanup, "passed": False}
            results["runs"].append(result)
            if negative:
                if (completed.returncode != 1 or stdout or
                        "DGLES2 CGLCreatePBuffer: 10005 invalid drawable" not in stderr or
                        "FAIL: create Nokia offscreen surface (EGL=0x3003)" not in stderr):
                    raise ValueError("control did not reproduce the expected CGL PBuffer failure")
            else:
                identity = validate_result(api, completed.returncode, stdout, stderr,
                                           backend=backend, cleanup=cleanup,
                                           renderer=args.renderer if linux else None)
                result["graphics_identity"] = identity
                observed_renderer = identity["GL_RENDERER"]
                if results.setdefault("renderer", observed_renderer) != observed_renderer:
                    raise ValueError("renderer changed between positive graphics cases")
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
    if results["passed"]:
        print(f"GL_RENDERER={results['renderer']}", flush=True)
    print(f"Host-only evidence: {out}", flush=True)
    if failure:
        raise SystemExit(f"FAIL: {failure}")


if __name__ == "__main__":
    main()
