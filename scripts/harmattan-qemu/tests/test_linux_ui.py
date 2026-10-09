"""Synthetic host checks; these do not claim a guest boot or Linux UI result."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from test_arm64_systemui import host
from test_arm64_shell_smoke import host_log

SCRIPTS = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), SCRIPTS / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LINUX = load('linux-offscreen')
LAUNCHER = load('run-linux-ui')
SHELL = load('diagnose-arm64-shell')
RENDERER = 'llvmpipe (LLVM 19.1.7, 256 bits)'
try:
    IMAGE = LINUX.require_pillow()
except RuntimeError:
    IMAGE = None


class LinuxRendererTests(unittest.TestCase):
    def test_exact_renderer_with_original_lifecycle_gates(self):
        data = host().replace(b'Apple Test GPU', RENDERER.encode())
        self.assertTrue(SHELL.systemui.validate_host(data, renderer=RENDERER)['workers_joined'])
        live = host(True).replace(b'Apple Test GPU', RENDERER.encode())
        self.assertTrue(SHELL.systemui.validate_host(live, live=True, renderer=RENDERER)['shutdown_summary_pending'])
        desktop = host_log().replace(b'Apple Test GPU', RENDERER.encode())
        self.assertTrue(SHELL.validate_desktop_host(desktop, renderer=RENDERER)['workers_joined'])
        self.assertTrue(SHELL.validate_live_host(b'\n'.join(desktop.splitlines()[:5]), renderer=RENDERER)['shutdown_summary_pending'])
        for bad in (data + b'warning\n', data.replace(b'faults=0', b'faults=1'),
                    data.replace(b'rejects=0', b'rejects=1'), data.replace(b'workers=joined', b'workers=pending'),
                    data.replace(b'19.1.7', b'19.1.8'), data.replace(b'disconnect client=2', b'disconnect client=3'),
                    data.replace(b'N00_GLES disconnect client=0\n', b'')):
            with self.subTest(data=bad[-80:]), self.assertRaises(ValueError):
                SHELL.systemui.validate_host(bad, renderer=RENDERER)
        # Merely running on Linux never changes the macOS default gate.
        with self.assertRaises(ValueError):
            SHELL.systemui.validate_host(data)
        self.assertTrue(SHELL.systemui.validate_host(host())['workers_joined'])

    def test_invalid_or_unpinned_renderer_fails(self):
        for renderer in ('Apple Test GPU', 'llvmpipe', 'llvmpipe ()', 'llvmpipe (x)\n',
                         'llvmpipe (x\x00)', 'llvmpipe (é)', '.*'):
            with self.subTest(renderer=renderer), self.assertRaises(ValueError):
                SHELL.systemui.renderer_pattern(renderer)

    def test_linux_configuration_is_explicit_bounded_and_offline(self):
        args = SimpleNamespace(host_backend='linux-offscreen', host_renderer=RENDERER,
            systemui_attempts=30, network='off', audio='off', ca_certificates='off',
            profile=None, boot_animation=None, power='off', call_simulation='off',
            lockscreen='off', startup_waits='ready', interactive=True, exit_on_ready=True,
            exercise_keyboard=False, exercise_transitions=False)
        command = ['qemu', '-display', 'none', '-nic', 'none', '-snapshot']
        with patch.object(SHELL.sys, 'platform', 'linux'), patch.object(SHELL.linux_offscreen, 'require_pillow'):
            self.assertTrue(SHELL.validate_host_configuration(args, command))
            with self.assertRaises(ValueError):
                SHELL.validate_host_configuration(args, command[:-1])
            for key, value in (('network', 'user'), ('profile', Path('profile')),
                               ('audio', 'pulse'), ('startup_waits', 'fixed'),
                               ('exit_on_ready', False), ('host_renderer', None)):
                with self.subTest(key=key), self.assertRaises(ValueError):
                    SHELL.validate_host_configuration(SimpleNamespace(**(vars(args) | {key: value})), command)
            for extra in (['-netdev', 'user,id=net0'], ['-qmp', 'tcp:localhost:1234'],
                          ['-nic', 'user'], ['-display', 'gtk']):
                with self.subTest(extra=extra), self.assertRaises(ValueError):
                    SHELL.validate_host_configuration(args, command + extra)
        cocoa = SimpleNamespace(**(vars(args) | {'host_backend': 'cocoa', 'host_renderer': None, 'systemui_attempts': 15}))
        self.assertFalse(SHELL.validate_host_configuration(cocoa, command))
        with self.assertRaises(ValueError):
            SHELL.validate_host_configuration(SimpleNamespace(**(vars(cocoa) | {'host_renderer': RENDERER})), command)


@unittest.skipUnless(hasattr(os, 'mkfifo'), 'requires POSIX FIFOs')
class LinuxPipeTests(unittest.TestCase):
    def test_bidirectional_private_transport_and_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / 'serial'
            serial = LINUX.PipeSerial(base, time.monotonic() + 2)
            try:
                for path in serial.paths:
                    self.assertTrue(stat.S_ISFIFO(path.stat().st_mode))
                    self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                to_guest = os.open(str(base) + '.in', os.O_RDWR | os.O_NONBLOCK)
                from_guest = os.open(str(base) + '.out', os.O_RDWR | os.O_NONBLOCK)
                try:
                    serial.sendall(b'guest command\n')
                    self.assertEqual(os.read(to_guest, 100), b'guest command\n')
                    os.write(from_guest, b'guest reply\n')
                    self.assertEqual(serial.recv(100), b'guest reply\n')
                finally:
                    os.close(to_guest)
                    os.close(from_guest)
            finally:
                serial.close()
                serial.close()
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_partial_setup_preserves_existing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / 'serial'
            existing = Path(str(base) + '.out')
            existing.write_text('keep me')
            with self.assertRaises(FileExistsError):
                LINUX.PipeSerial(base, time.monotonic() + 1)
            self.assertFalse(Path(str(base) + '.in').exists())
            self.assertEqual(existing.read_text(), 'keep me')

    def test_writes_expire_instead_of_waiting_forever(self):
        with tempfile.TemporaryDirectory() as tmp:
            serial = LINUX.PipeSerial(Path(tmp) / 'serial', time.monotonic() - 1)
            try:
                with self.assertRaises(TimeoutError):
                    serial.sendall(b'command')
            finally:
                serial.close()


@unittest.skipUnless(IMAGE, 'Pillow is an optional Linux UI runtime dependency')
class LinuxCaptureTests(unittest.TestCase):
    def test_png_preserves_every_rgb_byte_and_records_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            ppm, png = Path(tmp) / 'capture.ppm', Path(tmp) / 'capture.png'
            pixels = bytes(range(256)) * 3
            source = b'P6\n16 16\n255\n' + pixels
            ppm.write_bytes(source)
            LINUX.export_png(ppm, png)
            with IMAGE.open(png) as image:
                self.assertEqual(image.size, (16, 16))
                self.assertEqual(image.tobytes(), pixels)
            record = json.loads(png.with_suffix('.png.provenance.json').read_text())
            self.assertEqual(record['dimensions'], [16, 16])
            self.assertTrue(record['pixel_bytes_identical'])
            self.assertEqual(record['rgb_sha256'], hashlib.sha256(pixels).hexdigest())
            self.assertEqual(record['source_sha256'], hashlib.sha256(source).hexdigest())
            self.assertEqual(ppm.read_bytes(), source)

    def test_changed_pixel_or_wrong_source_mode_cannot_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            ppm, png = Path(tmp) / 'capture.ppm', Path(tmp) / 'capture.png'
            ppm.write_bytes(b'P6\n2 1\n255\n' + bytes((1, 2, 3, 4, 5, 6)))
            original_save = IMAGE.Image.save
            def changed_save(image, *args, **kwargs):
                changed = image.copy()
                changed.putpixel((0, 0), (0, 0, 0))
                original_save(changed, *args, **kwargs)
            with patch.object(IMAGE.Image, 'save', changed_save), self.assertRaises(ValueError):
                LINUX.export_png(ppm, png)
            self.assertFalse(png.with_suffix('.png.provenance.json').exists())
            ppm.write_bytes(b'P5\n2 1\n255\n\x00\xff')
            with self.assertRaises(ValueError):
                LINUX.export_png(ppm, png)


class LinuxPollingTests(unittest.TestCase):
    def test_guest_retry_budget_retains_default_and_failure(self):
        source = (SCRIPTS / 'diagnose-shell-guest.sh').read_text()
        start = source.index('        systemui_attempts=')
        end = source.index('\n        ;;', start)
        snippet = source[start:end]
        with tempfile.TemporaryDirectory() as tmp:
            snippet = snippet.replace('/tmp/n00-systemui-ready.log', str(Path(tmp) / 'ready.log'))
            # The real polling loop/check runs against a synthetic service that
            # supplies both nonzero D-Bus values only on its twentieth attempt.
            script = '''set -eu
count=0
ready=0
sleep() { :; }
report_systemui() {
    count=$((count + 1))
    if [ "$count" -ge 20 ]; then printf 'uint32 1\\nuint32 2\\n'; fi
    return 0
}
''' + snippet
            for budget, expected in ((None, 1), ('15', 1), ('30', 0), ('31', 2), ('0', 2)):
                env = {k: v for k, v in os.environ.items() if k != 'N00_UI_SYSTEMUI_ATTEMPTS'}
                if budget:
                    env['N00_UI_SYSTEMUI_ATTEMPTS'] = budget
                result = subprocess.run(['sh', '-c', script], env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, expected, result.stderr)
                if expected == 0:
                    self.assertIn('used=20 budget=30', result.stdout)


class LinuxLauncherTests(unittest.TestCase):
    def fixture(self, root):
        # macOS temporary directories may use /var -> /private/var aliases.
        # Compare the same canonical paths that the public launcher selects.
        root = root.resolve()
        build, runtime, prepared = root / 'build', root / 'dgles/objs-x86_64', root / 'prepared'
        for path in (build / 'meson-info', runtime, prepared):
            path.mkdir(parents=True)
        (build / 'meson-info/intro-buildoptions.json').write_text(json.dumps([
            {'name': 'n00_dgles_dir', 'value': str(runtime.parent)}]))
        for name in ('qemu-system-arm', 'qemu-img'):
            path = build / name
            path.write_bytes(b'\x7fELFsynthetic test fixture, never executed')
            path.chmod(0o700)
        for name in ('libEGL.so', 'libGLES_CM.so', 'libGLESv2.so'):
            (runtime / name).write_bytes(b'synthetic fixture, never loaded')
        for name in ('harmattan-pr1.3.raw', 'zImage-2.6.32.26-qemu', 'pr1.3-rootfs-qemu-rescue.ext4'):
            (prepared / name).write_bytes(b'synthetic guest fixture, never booted')
        args = ['--build-root', str(build), '--dgles-runtime', str(runtime), '--prepared-root', str(prepared),
                '--renderer', RENDERER, '--output', str(root / 'run')]
        return args, prepared

    def test_disposable_offline_command_and_both_modes(self):
        for mode in ('startup', 'usability'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                args, prepared = self.fixture(root)
                args += ['--mode', mode]
                before = {path.name: path.read_bytes() for path in prepared.iterdir()}
                commands = []
                def controller(command, env, log, timeout):
                    commands.append((command, env))
                    ui = root / 'run/ui'
                    ui.mkdir()
                    name = 'startup-result.json' if mode == 'startup' else 'keyboard-result.json'
                    (ui / name).write_text('{"passed": true}')
                    return 0
                kernel_sha = hashlib.sha256((prepared / 'zImage-2.6.32.26-qemu').read_bytes()).hexdigest()
                with patch.dict(os.environ, {}, clear=True), patch.object(LAUNCHER.sys, 'platform', 'linux'), \
                     patch.object(LAUNCHER, 'KERNEL_SHA256', kernel_sha), \
                     patch.object(LAUNCHER.linux_offscreen, 'require_pillow'), \
                     patch.object(LAUNCHER.subprocess, 'run') as create, \
                     patch.object(LAUNCHER, 'run_controller', side_effect=controller), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(LAUNCHER.main(args), 0)
                create_args = create.call_args.args[0]
                self.assertEqual(create_args[1:8], ['create', '-q', '-f', 'qcow2', '-F', 'raw', '-b'])
                self.assertEqual(create_args[8], str(prepared / 'harmattan-pr1.3.raw'))
                command, env = commands[0]
                qemu = command[command.index('--') + 1:]
                self.assertEqual(qemu[qemu.index('-nic') + 1], 'none')
                self.assertEqual(qemu[qemu.index('-display') + 1], 'none')
                self.assertIn('-snapshot', qemu)
                self.assertIn('format=qcow2,file=', qemu[qemu.index('-drive') + 1])
                self.assertNotIn(str(prepared / 'harmattan-pr1.3.raw'), qemu[qemu.index('-drive') + 1])
                self.assertIn('--host-backend', command)
                self.assertEqual(env['LIBGL_ALWAYS_SOFTWARE'], '1')
                self.assertEqual(env['HARMATTAN_ADAPTATION_LIBDIR'], str(prepared / 'overlay/usr/lib'))
                self.assertEqual({path.name: path.read_bytes() for path in prepared.iterdir()}, before)
                record = json.loads((root / 'run/launch-result.json').read_text())
                self.assertTrue(record['passed'])
                self.assertTrue(record['base_metadata_unchanged'])

    def test_changed_base_or_missing_controller_acceptance_fails(self):
        for changed in (False, True):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                args, prepared = self.fixture(root)
                kernel_sha = hashlib.sha256((prepared / 'zImage-2.6.32.26-qemu').read_bytes()).hexdigest()
                def controller(*unused):
                    if changed:
                        (prepared / 'harmattan-pr1.3.raw').write_bytes(b'changed')
                        (root / 'run/ui').mkdir()
                        (root / 'run/ui/startup-result.json').write_text('{"passed": true}')
                    return 0
                with patch.dict(os.environ, {}, clear=True), patch.object(LAUNCHER.sys, 'platform', 'linux'), \
                     patch.object(LAUNCHER, 'KERNEL_SHA256', kernel_sha), \
                     patch.object(LAUNCHER.linux_offscreen, 'require_pillow'), \
                     patch.object(LAUNCHER.subprocess, 'run'), \
                     patch.object(LAUNCHER, 'run_controller', side_effect=controller), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(LAUNCHER.main(args), 1)
                self.assertFalse(json.loads((root / 'run/launch-result.json').read_text())['passed'])

    def test_mismatched_runtime_or_kernel_fails_before_execution(self):
        for mismatch in ('runtime', 'kernel'):
            with self.subTest(mismatch=mismatch), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                args, prepared = self.fixture(root)
                if mismatch == 'runtime':
                    (root / 'build/meson-info/intro-buildoptions.json').write_text('[]')
                with patch.dict(os.environ, {}, clear=True), patch.object(LAUNCHER.sys, 'platform', 'linux'), \
                     patch.object(LAUNCHER.linux_offscreen, 'require_pillow'), \
                     patch.object(LAUNCHER.subprocess, 'run') as run, contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as error:
                        LAUNCHER.main(args)
                    self.assertEqual(error.exception.code, 2)
                    run.assert_not_called()
                self.assertFalse((root / 'run').exists())

    @unittest.skipUnless(sys.platform == 'linux', 'Linux process-group lifecycle')
    def test_controller_timeout_reaps_its_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            pidfile = Path(tmp) / 'pid'
            program = 'import os, pathlib, time; pathlib.Path(' + repr(str(pidfile)) + ').write_text(str(os.getpid())); time.sleep(20)'
            with self.assertRaises(TimeoutError):
                LAUNCHER.run_controller([sys.executable, '-c', program], os.environ.copy(), Path(tmp) / 'log', 1)
            pid = int(pidfile.read_text())
            with self.assertRaises(ProcessLookupError):
                os.kill(pid, 0)

    @unittest.skipUnless(sys.platform == 'linux', 'Linux process-group lifecycle')
    def test_timeout_kills_term_ignoring_descendant_after_leader_exits(self):
        for early_exit in (False, True):
            with self.subTest(early_exit=early_exit), tempfile.TemporaryDirectory() as tmp:
                pidfile = Path(tmp) / 'grandchild-pid'
                child = ("import os, pathlib, signal, time; "
                         "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                         f"pathlib.Path({str(pidfile)!r}).write_text(str(os.getpid())); "
                         "time.sleep(20)")
                leader = ("import os, pathlib, subprocess, sys, time\n"
                          f"subprocess.Popen([sys.executable, '-c', {child!r}])\n"
                          f"while not pathlib.Path({str(pidfile)!r}).exists(): time.sleep(.01)\n"
                          + ("os._exit(7)\n" if early_exit else "time.sleep(20)\n"))
                pid = None
                try:
                    with self.assertRaises(TimeoutError):
                        LAUNCHER.run_controller([sys.executable, '-c', leader], os.environ.copy(),
                                                Path(tmp) / 'log', 1)
                    pid = int(pidfile.read_text())
                    # An orphan may remain briefly as an init-owned zombie;
                    # neither a zombie nor an absent PID is a running QEMU.
                    proc = Path(f'/proc/{pid}/stat')
                    for _ in range(100):
                        if not proc.exists() or proc.read_text().split(') ', 1)[1].startswith('Z '):
                            break
                        time.sleep(.01)
                    else:
                        self.fail('controller left its SIGTERM-ignoring descendant running')
                finally:
                    if pid is None and pidfile.exists():
                        pid = int(pidfile.read_text())
                    if pid is not None:
                        try:
                            os.kill(pid, 9)
                        except ProcessLookupError:
                            pass


if __name__ == '__main__':
    unittest.main()
