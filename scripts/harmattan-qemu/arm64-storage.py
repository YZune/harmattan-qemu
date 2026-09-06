"""Private persistent disks, exclusive ownership and explicit guest flushing."""
import fcntl
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import time


FORMAT = 'harmattan-private-profile-1'
CAPACITY = 32 * 1024 ** 3


def write_json(path, value):
    fd, name = tempfile.mkstemp(prefix='.state-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def persistent_command(command, disk):
    if command.count('-snapshot') != 1 or command.count('-drive') != 1:
        raise ValueError('profile requires the launcher\'s single-drive snapshot command')
    index = command.index('-drive') + 1
    if index >= len(command) or not command[index].startswith('if=sd,format=qcow2,file='):
        raise ValueError('unrecognized guest drive')
    value = str(disk)
    if any(char in value for char in '\r\n\x00'):
        raise ValueError('invalid profile disk path')
    result = list(command)
    result[index] = 'if=sd,format=qcow2,file=' + value.replace(',', ',,')
    result.remove('-snapshot')
    return result


class Profile:
    def __init__(self, path, source, image_tool):
        self.fd = None
        path, source = Path(path), Path(source)
        if path.is_symlink():
            raise ValueError('profile directory must not be a symlink')
        self.path = path.resolve()
        self.image_tool = str(image_tool)
        fresh = not self.path.exists()
        if fresh:
            self.path.mkdir(mode=0o700, parents=True)
        self.disk = self.path / 'disk.qcow2'
        self.base = self.path / 'base.raw'
        self.state_path = self.path / 'profile.json'
        try:
            # Do not import or overwrite an arbitrary existing directory.
            if not fresh and not self.state_path.is_file():
                raise ValueError('existing directory is not a complete Harmattan profile')
            for name in ('profile.json', 'base.raw', 'disk.qcow2', 'checkpoint.qcow2', 'lock'):
                target = self.path / name
                if target.is_symlink() or (target.exists() and not target.is_file()):
                    raise ValueError('profile contains a non-regular file: ' + name)
            self.fd = os.open(self.path / 'lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            try:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError('profile is already open; close its running guest first') from exc
            if fresh:
                if not source.is_file() or not 0 < source.stat().st_size <= CAPACITY:
                    raise ValueError('source disk must be a nonempty raw disk of at most 32 GiB')
                subprocess.run(['/bin/cp', '-c', str(source), str(self.base)], check=True)
                self.base.chmod(0o400)
                subprocess.run([self.image_tool, 'create', '-q', '-f', 'qcow2', '-F', 'raw',
                                '-b', 'base.raw', 'disk.qcow2', str(CAPACITY)], cwd=self.path, check=True)
                self.disk.chmod(0o600)
                self.state = {'format': FORMAT, 'state': 'clean', 'sessions': 0,
                              'base_bytes': self.base.stat().st_size,
                              'scope': 'private system and home disk; not VM CPU/RAM save-state'}
                write_json(self.state_path, self.state)
            else:
                self.state = json.loads(self.state_path.read_text())
            self.validate()
            # Preserve the previous disk state before opening it for writes.
            # This file is a manual recovery checkpoint, never auto-restored.
            if fresh or self.state['state'] == 'clean':
                fd, temporary = tempfile.mkstemp(prefix='.checkpoint-', dir=self.path)
                os.close(fd)
                try:
                    subprocess.run(['/bin/cp', '-c', str(self.disk), temporary], check=True)
                    os.replace(temporary, self.path / 'checkpoint.qcow2')
                finally:
                    if os.path.exists(temporary):
                        os.unlink(temporary)
            if self.state['state'] != 'clean':
                print('Previous profile exit was unclean; retaining its disk and checkpoint for guest journal recovery.', flush=True)
            self.state.update(state='active', sessions=self.state['sessions'] + 1)
            write_json(self.state_path, self.state)
        except BaseException:
            self.close()
            raise

    def validate(self):
        if self.state.get('format') != FORMAT or self.state.get('state') not in ('clean', 'active'):
            raise ValueError('unsupported profile state')
        if type(self.state.get('sessions')) is not int or self.state['sessions'] < 0:
            raise ValueError('invalid profile session counter')
        if self.base.stat().st_size != self.state.get('base_bytes') or not 0 < self.base.stat().st_size <= CAPACITY:
            raise ValueError('private profile base size changed')
        if self.base.stat().st_mode & 0o222:
            raise ValueError('private profile base must remain read-only')
        info = json.loads(subprocess.check_output(
            [self.image_tool, 'info', '-f', 'qcow2', '--output=json', str(self.disk)], text=True))
        if (info.get('format') != 'qcow2' or info.get('virtual-size') != CAPACITY or
                info.get('backing-filename-format') != 'raw' or
                Path(info.get('full-backing-filename', '')).resolve() != self.base):
            raise ValueError('profile must use its own fixed raw backing disk')
        if info.get('format-specific', {}).get('data', {}).get('data-file'):
            raise ValueError('external qcow2 data files are unsupported')
        subprocess.run([self.image_tool, 'check', '-q', '-f', 'qcow2', str(self.disk)], check=True)

    def finish(self, *, synced, exit_code):
        if not synced or exit_code != 0:
            raise ValueError('profile cannot be marked clean without guest sync and a successful QEMU exit')
        self.validate()
        with self.disk.open('rb') as stream:
            os.fsync(stream.fileno())
        self.state['state'] = 'clean'
        write_json(self.state_path, self.state)

    def close(self):
        if self.fd is not None:
            # Do not explicitly unlock: an inherited QEMU descriptor must keep
            # ownership if the controller is killed while QEMU is still alive.
            os.close(self.fd)
            self.fd = None


def prepare_guest(serial, process, log, display):
    serial.sendall(b"mount -t tmpfs -o size=128m,mode=1777 tmpfs /tmp && "
                   b"mount -t tmpfs -o size=32m,mode=1777 tmpfs /var/run; "
                   b"printf '\\nN00_STORAGE_RUNTIME_EXIT_%s\\n' $?; printf 'N00_STORAGE_RUNTIME_DONE\\n'\n")
    display.wait_serial(serial, process, log,
                        lambda data: display.has_line(data, b'N00_STORAGE_RUNTIME_DONE'), time.monotonic() + 30)
    lines = Path(log.name).read_bytes().replace(b'\r', b'').splitlines()
    if [line for line in lines if line.startswith(b'N00_STORAGE_RUNTIME_EXIT_')] != [b'N00_STORAGE_RUNTIME_EXIT_0']:
        raise ValueError('private profile runtime mounts failed')


def sync_guest(serial, process, log, display):
    serial.sendall(b"sync; printf '\\nN00_STORAGE_SYNC_EXIT_%s\\n' $?; printf 'N00_STORAGE_SYNC_DONE\\n'\n")
    display.wait_serial(serial, process, log,
                        lambda data: display.has_line(data, b'N00_STORAGE_SYNC_DONE'), time.monotonic() + 30)
    lines = Path(log.name).read_bytes().replace(b'\r', b'').splitlines()
    if [line for line in lines if line.startswith(b'N00_STORAGE_SYNC_EXIT_')] != [b'N00_STORAGE_SYNC_EXIT_0']:
        raise ValueError('guest filesystem sync failed')


def shutdown_requested(path):
    if not path.exists():
        return False
    if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode) or path.stat().st_size > 5:
        raise ValueError('invalid native shutdown request')
    return path.read_bytes() == b'sync\n'
