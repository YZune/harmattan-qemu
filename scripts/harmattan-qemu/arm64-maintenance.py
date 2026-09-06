"""An owned, bounded serial session for private guest maintenance."""
import importlib.util
from pathlib import Path
import re
import socket
import subprocess
import time


def sibling(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


display = sibling('smoke-arm64-display')
storage = sibling('arm64-storage')
network = sibling('arm64-network')


def completed(data, tag):
    lines = data.replace(b'\r', b'').splitlines()
    exits = [line for line in lines if line.startswith((tag + '_EXIT_').encode())]
    if exits != [(tag + '_EXIT_0').encode()] or lines.count((tag + '_DONE').encode()) != 1:
        raise ValueError('guest command failed: ' + tag)
    return data.replace(b'\r', b'')


class Session:
    def __init__(self, command, output, profile=None, networking=False):
        self.command, self.output, self.profile = command, Path(output), profile
        self.networking = networking
        self.process = self.log = self.errors = self.serial = self.child = None
        self.ready = False

    def __enter__(self):
        self.output.mkdir(parents=True, exist_ok=False)
        try:
            self.log = (self.output / 'serial.log').open('xb')
            self.errors = (self.output / 'qemu-stderr.log').open('xb')
            self.serial, self.child = socket.socketpair()
            self.process = subprocess.Popen(self.command + ['-qmp', 'stdio', '-chardev',
                f'socket,id=n00serial,fd={self.child.fileno()}', '-serial', 'chardev:n00serial', '-monitor', 'none'],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.errors, env=display.qemu_environment(),
                pass_fds=(self.child.fileno(),) + ((self.profile.fd,) if self.profile else ()), bufsize=0)
            self.child.close()
            deadline = time.monotonic() + 120
            self.qmp = display.QMP(self.process, deadline)
            display.wait_serial(self.serial, self.process, self.log,
                lambda data: b'shell ready' in data and b'/ # ' in data, deadline)
            self.serial.sendall(b"dmesg -n 1; stty -echo; PS2=''; printf '\\nN00_MAINTENANCE_SHELL\\n'\n")
            self.wait('N00_MAINTENANCE_SHELL', deadline)
            # The SDK UART can discard a burst prefix on wake. Match the UI
            # controller: keep this control UART awake while CPU WFI stays on.
            self.serial.sendall(b"test -f /sys/devices/platform/serial8250.2/sleep_timeout && "
                b"printf '0\\n' > /sys/devices/platform/serial8250.2/sleep_timeout && "
                b"test \"$(cat /sys/devices/platform/serial8250.2/sleep_timeout)\" = 0 && "
                b"printf '\\nN00_MAINTENANCE_UART_AWAKE\\n'\n")
            self.wait('N00_MAINTENANCE_UART_AWAKE', deadline)
            if self.profile:
                storage.prepare_guest(self.serial, self.process, self.log, display)
            if self.networking:
                self.network = network.configure(self.serial, self.process, self.log, deadline, display)
            self.ready = True
            return self
        except BaseException:
            self.close()
            raise

    def wait(self, tag, deadline):
        display.wait_serial(self.serial, self.process, self.log,
            lambda data: display.has_line(data, tag.encode()), deadline)

    def run(self, script, tag, timeout=120):
        if not re.fullmatch(r'N00_[A-Z0-9_]+', tag) or not 0 < timeout <= 600:
            raise ValueError('invalid maintenance command tag or timeout')
        payload = script.encode().hex()
        if len(payload) > 262144:
            raise ValueError('maintenance script exceeds 128 KiB')
        self.log.flush()
        start = self.log.tell()
        self.serial.sendall(f"perl -ne 'chomp; print pack(\"H*\",$_)' > /tmp/n00-maintenance.sh <<'{tag}_SCRIPT'\n".encode())
        for offset in range(0, len(payload), 76):
            self.serial.sendall(payload[offset:offset + 76].encode() + b'\n')
        self.serial.sendall((f"{tag}_SCRIPT\nsh /tmp/n00-maintenance.sh; "
            f"printf '\\n{tag}_EXIT_%s\\n' $?; printf '{tag}_DONE\\n'\n").encode())
        self.wait(tag + '_DONE', time.monotonic() + timeout)
        with Path(self.log.name).open('rb') as stream:
            stream.seek(start)
            return completed(stream.read(), tag)

    def __exit__(self, kind, value, traceback):
        try:
            if self.ready:
                if self.process.poll() is not None:
                    raise RuntimeError('guest exited before the maintenance flush')
                # A rejected package may leave a partial install. Flush it and
                # keep dpkg's real state; a clean disk is not an install success.
                storage.sync_guest(self.serial, self.process, self.log, display)
                self.qmp.deadline = time.monotonic() + 30
                self.qmp.call('stop')
                self.qmp.call('quit')
                code = self.process.wait(timeout=10)
                self.errors.flush()
                display.validate_display_host(Path(self.errors.name).read_bytes(), code)
                if self.profile:
                    self.profile.finish(synced=True, exit_code=code)
        finally:
            self.close()

    def close(self):
        if self.process:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
            self.process.stdin.close()
            self.process.stdout.close()
        for stream in (self.serial, self.child, self.log, self.errors):
            if stream:
                stream.close()
