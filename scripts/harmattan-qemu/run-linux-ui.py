#!/usr/bin/env python3
"""Offline Linux experiment using original Home startup/acceptance controllers.

The raw image and helper rootfs are only opened read-only. Each invocation owns a
new qcow2 overlay, additionally protected by QEMU -snapshot. No Cocoa, external
control socket, networking, audio, or physical-GPU requirement is introduced.
"""
import argparse
import hashlib
import importlib.util
import json
import math
import os
import select
import signal
from pathlib import Path
import subprocess
import sys
import tempfile
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SCRIPTS = HERE
KERNEL_SHA256 = '4eade6a330b7e01d6dafe8cf22ad5b3c5024c09776036f5329604c03b302546e'
UI_SPEC = importlib.util.spec_from_file_location('systemui', HERE / 'arm64-systemui.py')
systemui = importlib.util.module_from_spec(UI_SPEC)
UI_SPEC.loader.exec_module(systemui)
LINUX_SPEC = importlib.util.spec_from_file_location('linux_offscreen', HERE / 'linux-offscreen.py')
linux_offscreen = importlib.util.module_from_spec(LINUX_SPEC)
LINUX_SPEC.loader.exec_module(linux_offscreen)


def fingerprint(path):
    st = path.stat()
    return {'size': st.st_size, 'blocks': st.st_blocks, 'mtime_ns': st.st_mtime_ns,
            'ctime_ns': st.st_ctime_ns, 'device': st.st_dev, 'inode': st.st_ino}


def run_controller(command, env, log_path, timeout):
    """Bound the controller and reap only this run's process group on failure."""
    process = None
    try:
        with log_path.open('xb') as log:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       env=env, bufsize=0, start_new_session=True)
            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('Linux UI controller exceeded its bounded runtime')
                if not select.select([process.stdout], [], [], min(remaining, .2))[0]:
                    continue
                chunk = os.read(process.stdout.fileno(), 65536)
                if not chunk:
                    return process.wait(timeout=max(.1, deadline - time.monotonic()))
                log.write(chunk)
                log.flush()
                sys.stdout.buffer.write(chunk)
                sys.stdout.buffer.flush()
    finally:
        if process is not None:
            # Also stop descendants if a crashed controller has already exited
            # while its QEMU child still holds the output pipe open.
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            if process.poll() is None:
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)
            process.stdout.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-root', type=Path, required=True)
    parser.add_argument('--dgles-runtime', type=Path, required=True)
    parser.add_argument('--prepared-root', type=Path, required=True, help='prepare-guest.py output directory')
    parser.add_argument('--helper-workspace', type=Path, help='guest helper build directory; defaults beside QEMU build')
    parser.add_argument('--renderer', required=True, help='exact llvmpipe renderer from the real DGLES smoke')
    parser.add_argument('--mode', choices=('startup', 'usability'), default='startup')
    parser.add_argument('--timeout', type=float, default=600)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--prepare-only', action='store_true', help='validate inputs and build guest helpers; do not launch QEMU')
    args = parser.parse_args(argv)
    if sys.platform != 'linux' or not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error('Linux host and positive timeout are required')
    for key in ('HARMATTAN_USER_PROFILE', 'HARMATTAN_PREBUILT_HELPERS', 'HARMATTAN_APP_CONTENTS'):
        if os.environ.get(key):
            parser.error(f'unset {key}: only isolated source-built snapshots are supported')
    try:
        systemui.renderer_pattern(args.renderer)
        linux_offscreen.require_pillow()
    except (ValueError, RuntimeError) as error:
        parser.error(str(error))
    build, runtime = args.build_root.resolve(), args.dgles_runtime.resolve()
    prepared = args.prepared_root.resolve()
    helpers = (args.helper_workspace or build.parent / 'linux-guest-helpers').resolve()
    options_path = build / 'meson-info/intro-buildoptions.json'
    if not options_path.is_file():
        parser.error('build manifest is required to pin the selected DGLES runtime')
    selected_dgles = next((item['value'] for item in json.loads(options_path.read_text())
                           if item['name'] == 'n00_dgles_dir'), None)
    if not selected_dgles or (Path(selected_dgles) / 'objs-x86_64').resolve() != runtime:
        parser.error('DGLES runtime differs from the selected QEMU build manifest')
    raw = prepared / 'harmattan-pr1.3.raw'
    kernel = prepared / 'zImage-2.6.32.26-qemu'
    rootfs = prepared / 'pr1.3-rootfs-qemu-rescue.ext4'
    qemu, image_tool = build / 'qemu-system-arm', build / 'qemu-img'
    for path in (raw, kernel, rootfs, qemu, image_tool, *(runtime / n for n in ('libEGL.so', 'libGLES_CM.so', 'libGLESv2.so'))):
        if not path.is_file():
            parser.error(f'missing input: {path}')
    if hashlib.sha256(kernel.read_bytes()).hexdigest() != KERNEL_SHA256:
        parser.error('pinned original SDK kernel hash mismatch')
    for tool in (qemu, image_tool):
        with tool.open('rb') as executable:
            if executable.read(4) != b'\x7fELF' or not os.access(tool, os.X_OK):
                parser.error(f'Linux ELF executable required: {tool}')
    if not 0 < raw.stat().st_size <= 32 * 1024**3:
        parser.error('raw guest must be nonempty and at most 32 GiB')
    env = os.environ.copy()
    env.update(HARMATTAN_PORT_WORKSPACE=str(helpers),
               HARMATTAN_PUBLIC_ROOTFS=str(rootfs),
               HARMATTAN_ADAPTATION_LIBDIR=str(prepared / 'overlay/usr/lib'),
               HARMATTAN_UI_IDLE_PROFILE='wfi', HARMATTAN_UI_NETWORK='off',
               HARMATTAN_UI_AUDIO='off', HARMATTAN_UI_BOOT_ANIMATION='off',
               HARMATTAN_UI_SKIN='off', HARMATTAN_DGLES_RUNTIME_DIR=str(runtime),
               LIBGL_ALWAYS_SOFTWARE='1', GALLIUM_DRIVER='llvmpipe', LP_NUM_THREADS='2', EGL_PLATFORM='surfaceless')
    env['LD_LIBRARY_PATH'] = str(runtime) + (':' + env['LD_LIBRARY_PATH'] if env.get('LD_LIBRARY_PATH') else '')
    if args.prepare_only:
        before = {str(path): fingerprint(path) for path in (raw, kernel, rootfs)}
        try:
            for script, options in (('build-orientation-guest.sh', []), ('build-compositor-guest.sh', ['--handoff']),
                                    ('build-keyboard-probe.sh', [])):
                subprocess.run(['sh', str(SCRIPTS / script), *options], check=True, env=env, timeout=300)
        finally:
            if before != {str(path): fingerprint(path) for path in (raw, kernel, rootfs)}:
                raise RuntimeError('prepared input metadata changed during helper compilation')
        return 0
    if args.output:
        out = args.output.resolve()
        if any(c in str(out) for c in (',', '\n', '\r')):
            parser.error('output path must not contain commas or newlines')
        out.mkdir(mode=0o700, parents=True, exist_ok=False)
    else:
        runs = REPO / 'extracted/linux-ui'
        runs.mkdir(parents=True, exist_ok=True)
        out = Path(tempfile.mkdtemp(prefix='run.', dir=runs)).resolve()
    if any(c in str(out) for c in (',', '\n', '\r')):
        parser.error('output path must not contain commas or newlines')
    env['MESA_SHADER_CACHE_DIR'] = str(out / 'mesa-cache')
    (out / 'mesa-cache').mkdir(mode=0o700)
    base_before = {str(path): fingerprint(path) for path in (raw, kernel, rootfs)}
    overlay = out / 'pr13-32g.qcow2'
    qemu_args = [str(qemu), '-M', 'n00-port-spike', '-name', 'Harmattan PR1.3 Linux software-rendering experiment',
                 '-kernel', str(kernel), '-append', 'init=/sbin/preinit root=0xB302 rootfstype=ext4 rw rootdelay=2 hlt console=ttyS0,115200n8 omap3_die_id',
                 '-drive', f'if=sd,format=qcow2,file={overlay}', '-snapshot', '-display', 'none', '-rotate', '270',
                 '-no-reboot', '-nic', 'none']
    controller = [sys.executable, '-B', str(SCRIPTS / 'diagnose-arm64-shell.py'),
                  '--host-backend', 'linux-offscreen', '--host-renderer', args.renderer, '--systemui-attempts', '30',
                  '--output', str(out / 'ui'), '--timeout', str(args.timeout), '--rotation', '270',
                  '--startup-waits', 'ready', '--network', 'off', '--audio', 'off', '--ca-certificates', 'off',
                  '--browser-mode', 'original', '--power', 'off', '--call-simulation', 'off', '--lockscreen', 'off',
                  '--system-ui', 'on', '--clock', 'host', '--input-method', 'on', '--device-orientation', 'display',
                  '--compositor-animations', 'on', '--splash', 'off', '--display-handoff', 'on']
    controller += ['--interactive', '--exit-on-ready'] if args.mode == 'startup' else ['--exercise-keyboard', '--exercise-transitions']
    command = controller + ['--'] + qemu_args
    record = {'scope': 'Linux headless software-rendered original Home; no physical GPU/Cocoa/retail service graph acceptance',
              'mode': args.mode, 'command': command, 'host_renderer': args.renderer, 'network': 'off',
              'linux_systemui_polling_budget': 30,
              'transport': 'QMP stdio and private serial FIFOs; no socket/listener',
              'guest_backing_open': 'read-only qcow2 backing; disposable qcow2 plus -snapshot',
              'base_before': base_before, 'qemu_sha256': hashlib.sha256(qemu.read_bytes()).hexdigest(),
              'kernel_sha256': hashlib.sha256(kernel.read_bytes()).hexdigest(), 'passed': False}
    (out / 'launch.json').write_text(json.dumps(record, indent=2) + '\n')
    print(f'Linux headless UI evidence: {out}', flush=True)
    try:
        subprocess.run([str(image_tool), 'create', '-q', '-f', 'qcow2', '-F', 'raw', '-b', str(raw), str(overlay), '32G'],
                       check=True, env=env, timeout=30)
        # Helper compilation precedes the controller's guest deadline. Bound
        # that preparation too, while allowing the full requested guest budget.
        code = run_controller(command, env, out / 'controller.log', args.timeout + 300)
        record['controller_exit'] = code
        result_name = 'startup-result.json' if args.mode == 'startup' else 'keyboard-result.json'
        result_path = out / 'ui' / result_name
        if result_path.exists():
            record['controller_result'] = json.loads(result_path.read_text())
        record['passed'] = code == 0 and record.get('controller_result', {}).get('passed') is True
    except BaseException as error:
        record['failure'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        record['base_after'] = {str(path): fingerprint(path) for path in (raw, kernel, rootfs)}
        record['base_metadata_unchanged'] = base_before == record['base_after']
        record['passed'] &= record['base_metadata_unchanged']
        (out / 'launch-result.json').write_text(json.dumps(record, indent=2) + '\n')
    return 0 if record['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
