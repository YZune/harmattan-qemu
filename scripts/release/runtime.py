#!/usr/bin/env python3
"""Private app entry point: import prepared inputs, validate and run snapshots."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile

KERNEL_SHA256 = '4eade6a330b7e01d6dafe8cf22ad5b3c5024c09776036f5329604c03b302546e'
MAX_DISK = 32 * 1024**3


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inspect_disk(path):
    info = path.stat()
    if not path.is_file() or not 512 <= info.st_size <= MAX_DISK:
        raise ValueError('Expected a prepared raw disk of at most 32 GiB / 需要不超过 32 GiB 的已准备 raw 磁盘')
    with path.open('rb') as stream:
        mbr = stream.read(512)
        if mbr[510:] != b'\x55\xaa':
            raise ValueError('Missing MBR; a firmware file or QCOW2 is not a prepared raw disk / 缺少 MBR 分区表')
        partition = mbr[462:478]  # The boot command uses partition 2.
        start, sectors = struct.unpack_from('<II', partition, 8)
        if partition[4] != 0x83 or not start or not sectors or (start + sectors) * 512 > info.st_size:
            raise ValueError('Missing bounded Linux root partition 2 / 第二分区不是有效的 Linux 根分区')
        stream.seek(start * 512 + 1080)
        if stream.read(2) != b'\x53\xef':
            raise ValueError('Root partition 2 has no ext filesystem signature / 第二分区缺少 ext 文件系统标识')
    return {'bytes': info.st_size, 'mtime_ns': info.st_mtime_ns}


def data_home():
    return Path(os.environ.get('HARMATTAN_DATA_HOME',
        Path.home() / 'Library/Application Support/Harmattan QEMU')).expanduser().resolve()


def import_inputs(state, kernel, disk, replace=False):
    # Validate everything before creating a new profile. Never edit an input.
    kernel, disk = kernel.resolve(strict=True), disk.resolve(strict=True)
    if not kernel.is_file() or not 0 < kernel.stat().st_size < 32 * 1024**2 or digest(kernel) != KERNEL_SHA256:
        raise ValueError('Wrong guest kernel SHA-256 / 内核 SHA-256 不匹配')
    before = inspect_disk(disk)
    settings = state / 'inputs.json'
    if settings.exists() and not replace:
        raise ValueError('Inputs already configured; use --replace to retain the old profile and import another / 已配置系统资源')
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    inputs = state / 'inputs'
    inputs.mkdir(exist_ok=True, mode=0o700)
    # A failed staging directory is automatically removed; old profiles stay.
    with tempfile.TemporaryDirectory(prefix='.import-', dir=inputs) as staging:
        stage = Path(staging)
        shutil.copyfile(kernel, stage / 'kernel')
        subprocess.run(['/bin/cp', '-c', str(disk), str(stage / 'guest.raw')], check=True)
        if inspect_disk(disk) != before:
            raise ValueError('Source changed during import; stop its writer before retrying / 导入期间源磁盘发生变化')
        cloned = inspect_disk(stage / 'guest.raw')
        cloned['sha256'] = digest(stage / 'guest.raw')
        if digest(stage / 'kernel') != KERNEL_SHA256:
            raise ValueError('Kernel copy verification failed')
        name = stage.name.removeprefix('.')
        profile = inputs / name
        stage.rename(profile)
        record = {'schema_version': 1, 'profile': name, 'disk': cloned,
                  'kernel_sha256': KERNEL_SHA256,
                  'scope': 'prepared disk structure only; guest runtime checks original component identities'}
        # Atomic replacement; an interrupted import cannot point to half a copy.
        fd, temporary = tempfile.mkstemp(prefix='.settings-', dir=state)
        with os.fdopen(fd, 'w') as stream:
            json.dump(record, stream, indent=2)
            stream.write('\n')
        os.replace(temporary, settings)
    print('Inputs imported; original files unchanged / 导入完成，原文件未修改', flush=True)


def check(state):
    settings = state / 'inputs.json'
    if not settings.is_file():
        raise FileNotFoundError('Import a prepared raw disk and matching kernel first / 请先导入已准备的 raw 磁盘和对应内核')
    record = json.loads(settings.read_text())
    name = record['profile']
    if record.get('schema_version') != 1 or Path(name).name != name or not name.startswith('import-'):
        raise ValueError('Invalid local input manifest')
    profile = state / 'inputs' / name
    kernel, disk = profile / 'kernel', profile / 'guest.raw'
    if digest(kernel) != KERNEL_SHA256:
        raise ValueError('Imported kernel changed; re-import / 已导入的内核发生变化')
    current = inspect_disk(disk)
    if any(current[key] != record['disk'][key] for key in current):
        raise ValueError('Imported disk changed; re-import / 已导入磁盘发生变化，请重新导入')
    return kernel, disk


def run(state, contents, mode, skin, boot_animation=True):
    kernel, disk = check(state)
    state.mkdir(parents=True, exist_ok=True)
    # flock avoids overlapping launchers while preserving the user's source run.
    lock = (state / 'run.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise ValueError('This app already has an active session / 此应用已有运行中的会话') from None
    project = contents / 'Resources/project'
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('HARMATTAN_', 'N00_', 'PYTHON', 'DYLD_'))}
    # Keep QMP socket names under Darwin's 104-byte limit. Runs are retained
    # for diagnosis; record this task-owned path instead of cleaning /tmp broadly.
    workspace = Path(tempfile.mkdtemp(prefix='harmattan-run-', dir='/private/tmp'))
    (state / 'last-run.txt').write_text(str(workspace) + '\n')
    python_home = contents / 'Resources/python'
    env.update(PATH='/usr/bin:/bin:/usr/sbin:/sbin',
               PYTHONHOME=str(python_home), PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1',
               HARMATTAN_APP_CONTENTS=str(contents), HARMATTAN_UI_RUNTIME='responsive',
               HARMATTAN_PORT_WORKSPACE=str(workspace), HARMATTAN_PYTHON=str(contents / 'MacOS/python3'),
               HARMATTAN_KERNEL=str(kernel), HARMATTAN_GUEST_IMAGE=str(disk),
               HARMATTAN_PREBUILT_HELPERS=str(contents / 'Resources/helpers'),
               HARMATTAN_UI_SKIN=skin,
               HARMATTAN_UI_BOOT_ANIMATION='on' if boot_animation else 'off',
               # Bundled scripts deliberately fail if a builder path is reached.
               HARMATTAN_ARMEL_CLANG='/nonexistent/release-does-not-compile',
               HARMATTAN_DEBUGFS='/nonexistent/release-does-not-extract-link-inputs')
    return subprocess.call(['/bin/sh', str(project / 'scripts/harmattan-qemu/run-arm64-ui.sh'), mode], env=env)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--contents', type=Path, required=True)
    commands = parser.add_subparsers(dest='command', required=True)
    importer = commands.add_parser('import', help='Import a prepared disk; retail firmware reconstruction is not supported')
    importer.add_argument('--kernel', type=Path, required=True)
    importer.add_argument('--disk', type=Path, required=True)
    importer.add_argument('--replace', action='store_true')
    commands.add_parser('check')
    runner = commands.add_parser('run')
    runner.add_argument('--diagnostic', action='store_true')
    runner.add_argument('--no-frame', action='store_true')
    runner.add_argument('--no-boot-animation', action='store_true')
    args = parser.parse_args()
    state = data_home()
    try:
        if args.command == 'import':
            import_inputs(state, args.kernel, args.disk, args.replace)
        elif args.command == 'check':
            check(state)
            print('Prepared inputs available / 已配置系统资源')
        else:
            return run(state, args.contents.resolve(),
                       '--usability-headless-diagnostic' if args.diagnostic else 'interactive',
                       'off' if args.no_frame else 'frame', not args.no_boot_animation)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
