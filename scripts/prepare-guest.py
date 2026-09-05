#!/usr/bin/env python3
"""Prepare a private PR1.3 guest from two exact, user-supplied original media.

No download, SDK execution, host mount, sudo, device access or existing-image
write. Fixed slices are valid only after verifying the entire pinned input.
Nokia chunk/sparse format: ali1234's historical unlzo format description,
https://web.archive.org/web/20140805085933id_/http://al.robotfuzz.com/~al/maemo/unlzo
This implementation uses bounded liblzo decompression and sparse file writes.
"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import select
import shutil
import struct
import subprocess
import tarfile
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
MEDIA = json.loads((ROOT / 'docs/guest-media.json').read_text())
CHUNK = 4 * 1024**2
DISK_BYTES = 32 * 1024**3


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify(path, identity):
    if not path.is_file() or path.stat().st_size != identity['bytes'] or sha(path) != identity['sha256']:
        raise ValueError(f'Wrong size or SHA-256 / 大小或摘要不匹配: {path.name}')


def copy_range(source, target, offset, length, *, target_offset=0, sparse=False):
    if offset < 0 or length < 0 or offset + length > source.stat().st_size:
        raise ValueError('Source range is out of bounds')
    with source.open('rb') as src, target.open('r+b' if target.exists() else 'xb') as dst:
        src.seek(offset)
        dst.seek(target_offset)
        remaining = length
        while remaining:
            data = src.read(min(CHUNK, remaining))
            if not data:
                raise ValueError('Truncated source')
            if sparse and not data.strip(b'\0'):
                dst.seek(len(data), 1)
            else:
                dst.write(data)
            remaining -= len(data)
        if dst.tell() > os.fstat(dst.fileno()).st_size:
            dst.truncate()


def extract_slice(source, target, identity, offset_key='offset'):
    if target.exists():
        raise ValueError('Refusing to overwrite extracted input')
    copy_range(source, target, identity[offset_key], identity['bytes'])
    verify(target, identity)


def extract_member(archive, target, identity):
    with tarfile.open(archive) as tar:
        members = [m for m in tar.getmembers() if m.name == identity['member']]
        if len(members) != 1 or not members[0].isfile() or members[0].size != identity['bytes']:
            raise ValueError('Missing, duplicate or non-regular runtime member')
        with tar.extractfile(members[0]) as src, target.open('xb') as dst:
            shutil.copyfileobj(src, dst, CHUNK)
    verify(target, identity)


def sparse_ranges(header, maximum=4 * 1024**3):
    if len(header) != 0x2000:
        raise ValueError('Truncated sparse header')
    result, previous_end = [], 0
    for pos in range(0x40, 0x2000, 8):
        start, blocks = struct.unpack_from('<II', header, pos)
        if not start and not blocks:
            continue
        end = (start + blocks) * 512
        if not blocks or start * 512 < previous_end or end > maximum:
            raise ValueError('Overlapping, empty or oversized sparse range')
        result.append((start * 512, blocks * 512))
        previous_end = end
    if not result:
        raise ValueError('Empty sparse map')
    return result


def decompress_rootfs(payload, stream_path, rootfs, library):
    lzo = ctypes.CDLL(str(library))
    decompress = lzo.lzo1x_decompress_safe
    decompress.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p,
                           ctypes.POINTER(ctypes.c_size_t), ctypes.c_void_p]
    decompress.restype = ctypes.c_int
    total = 0
    with payload.open('rb') as src, stream_path.open('xb') as dst:
        while True:
            header = src.read(20)
            if len(header) != 20:
                raise ValueError('Missing Nokia chunk terminator')
            magic, reserved, compressed, packed, plain = struct.unpack('<5I', header)
            if magic != 0xb8c3b410 or reserved or compressed not in (0, 1):
                raise ValueError('Invalid Nokia chunk header')
            if not packed and not plain and not compressed:
                # The pinned payload has a 46-byte trailer after its terminator.
                if len(src.read(512)) > 511:
                    raise ValueError('Oversized chunk trailer')
                break
            if not 0 < packed <= 65536 or not 0 < plain <= 65536 or total + plain > 4 * 1024**3:
                raise ValueError('Unbounded Nokia chunk')
            data = src.read(packed)
            if len(data) != packed:
                raise ValueError('Truncated Nokia chunk')
            if compressed:
                output = ctypes.create_string_buffer(plain)
                size = ctypes.c_size_t(plain)
                if decompress(data, len(data), output, ctypes.byref(size), None) or size.value != plain:
                    raise ValueError('LZO decompression failed or length changed')
                data = output.raw
            elif packed != plain:
                raise ValueError('Raw chunk length mismatch')
            dst.write(data)
            total += plain
    with stream_path.open('rb') as src:
        ranges = sparse_ranges(src.read(0x2000))
    if 0x2000 + sum(length for _, length in ranges) != total:
        raise ValueError('Sparse payload size mismatch')
    cursor = 0x2000
    for offset, length in ranges:
        copy_range(stream_path, rootfs, cursor, length, target_offset=offset)
        cursor += length
    verify(rootfs, MEDIA['retail_rootfs'])


def partitions(disk):
    with disk.open('rb') as stream:
        mbr = stream.read(512)
    if len(mbr) != 512 or mbr[510:] != b'\x55\xaa':
        raise ValueError('Missing MBR')
    result = []
    for position in range(446, 494, 16):
        kind = mbr[position + 4]
        start, blocks = struct.unpack_from('<II', mbr, position + 8)
        if not blocks or (start + blocks) * 512 > disk.stat().st_size:
            raise ValueError('Invalid SDK partition')
        result.append((kind, start * 512, blocks * 512))
    expected = [(12, 63, 20980827), (131, 20980890, 20980890), (131, 41961780, 20948760)]
    if result != [(kind, start * 512, blocks * 512) for kind, start, blocks in expected]:
        raise ValueError('Unexpected SDK partition layout')
    return result


def debugfs(tool, filesystem, commands, log, *, write=False, cwd=None):
    # Only fixed guest paths and private staging paths enter this command file.
    batch = log.with_suffix('.commands')
    batch.write_text('\n'.join(commands) + '\n')
    args = [str(tool), *(['-w'] if write else []), '-f', str(batch), str(filesystem)]
    with log.open('wb') as output:
        subprocess.run(args, cwd=cwd, stdout=output, stderr=subprocess.STDOUT, check=True)
    text = log.read_text()
    if re.search(r'File not found|not a directory|already exists|Could not|No space|Usage:|Command not found|short read', text, re.I):
        raise ValueError(f'debugfs failed; inspect {log.name}')


def make_overlay(sdk_root, work, tool):
    stage = work / 'overlay'
    modules = stage / 'lib/modules'
    modules.mkdir(parents=True)
    commands = ['rdump /lib/modules/2.6.32.26 overlay/lib/modules']
    guest_files = ['etc/init/sgx.conf', 'usr/lib/libEGL.so.1.3.0',
                   'usr/lib/libGLES_CM.so.1.4.5', 'usr/lib/libGLESv2.so.1.4.9',
                   'usr/lib/xorg/modules/drivers/omapfb_drv.so']
    for name in guest_files:
        (stage / name).parent.mkdir(parents=True, exist_ok=True)
        commands.append(f'dump /{name} overlay/{name}')
    debugfs(tool, sdk_root, commands, work / 'adaptation.log', cwd=work)
    manifest = json.loads((ROOT / 'docs/inputs.json').read_text())['inputs']
    for name in guest_files[1:]:
        entry = next(item for item in manifest if item['path'].endswith('/' + name))
        if sha(stage / name) != entry['sha256']:
            raise ValueError('Extracted adaptation identity mismatch')
    if not (modules / '2.6.32.26/kfgles2.ko').is_file():
        raise ValueError('Missing QEMU graphics module')
    mapping = {'xorg-pr13-qemu.conf': 'etc/X11/xorg.conf',
               'start-pr13-qemu-ui.sh': 'usr/local/sbin/start-pr13-qemu-ui',
               'invoker-direct-qemu.sh': 'usr/local/libexec/harmattan-qemu/invoker-direct',
               'apply-pr13-ui-overlay.sh': 'usr/local/sbin/apply-pr13-qemu-ui-overlay'}
    for source, target in mapping.items():
        path = stage / target
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / 'scripts/harmattan-qemu' / source, path)
        path.chmod(0o755 if source.endswith('.sh') else 0o644)
    def owner(member):
        member.uid = member.gid = 0
        member.uname = member.gname = ''
        member.mtime = 1356998400
        return member
    archive = work / 'overlay.tar.gz'
    with tarfile.open(archive, 'w:gz') as tar:
        for path in sorted(stage.rglob('*')):
            if path.is_symlink() or not (path.is_file() or path.is_dir()):
                raise ValueError('Unexpected adaptation entry')
            tar.add(path, arcname=str(path.relative_to(stage)), recursive=False, filter=owner)
    return archive


PREPARE_INIT = '''#!/bin/sh
export PATH=/sbin:/bin:/usr/sbin:/usr/bin
set -eu
mount -t proc proc /proc
mount -o remount,rw /
mount -t sysfs sysfs /sys
mount -t devtmpfs devtmpfs /dev
exec </dev/ttyS0 >/dev/ttyS0 2>&1
dmesg -n 1
mkdir -p /dev/pts /tmp /var/run /home
mount -t devpts devpts /dev/pts
mount /dev/mmcblk0p3 /home
sh /harmattan-apply.sh /harmattan-overlay.tar.gz
rm /harmattan-apply.sh /harmattan-overlay.tar.gz /harmattan-prepare.sh
# Close the now-unlinked script before the read-only remount. Linux otherwise
# rejects the remount while init still holds this unlinked inode open.
exec /bin/sh -c '
set -eu
sync
umount /home
mount -o remount,ro /
echo HARMATTAN_PREPARE_COMPLETE
while :; do sleep 60; done
'
'''


def prepare_boot(qemu, disk, kernel, work):
    log = work / 'prepare-serial.log'
    env = {k: v for k, v in os.environ.items() if not k.startswith(('N00_', 'HARMATTAN_', 'DYLD_', 'PYTHON'))}
    frameworks = qemu.parent.parent / 'Frameworks'
    if not (frameworks / 'libEGL.1.dylib').is_file():
        raise ValueError('Use qemu-system-arm inside the complete prebuilt application')
    env['DYLD_LIBRARY_PATH'] = str(frameworks)
    env['HARMATTAN_DGLES_RUNTIME_DIR'] = str(frameworks)
    args = [str(qemu), '-M', 'n00-port-spike', '-kernel', str(kernel),
            '-append', 'init=/harmattan-prepare.sh root=0xB302 rootfstype=ext4 rw rootdelay=2 console=ttyS0,115200n8 omap3_die_id',
            '-drive', f'if=sd,format=raw,file={disk}', '-display', 'none',
            '-serial', 'stdio', '-monitor', 'none', '-nic', 'none', '-no-reboot']
    with log.open('wb') as output:
        process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, env=env)
        seen = b''
        deadline = time.monotonic() + 240
        try:
            while time.monotonic() < deadline:
                if select.select([process.stdout], [], [], 1)[0]:
                    block = os.read(process.stdout.fileno(), 65536)
                    if not block:
                        break
                    output.write(block)
                    output.flush()
                    seen = (seen + block)[-131072:]
                    if b'Kernel panic' in seen:
                        raise ValueError(f'Guest kernel panic; inspect {log.name}')
                    if b'\nHARMATTAN_PREPARE_COMPLETE\r\n' in seen or b'\nHARMATTAN_PREPARE_COMPLETE\n' in seen:
                        return
                if process.poll() is not None:
                    break
            raise ValueError(f'Guest preparation did not finish; inspect {log.name}')
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def prepare(args, work):
    print('1/6 Extracting pinned SDK runtime / 提取固定 SDK 运行时', flush=True)
    component = work / 'runtime.7z'
    extract_slice(args.sdk_exe, component, MEDIA['sdk']['runtime_component'])
    runtime = work / 'runtime.tar.gz'
    with runtime.open('xb') as output:
        subprocess.run([str(args.sevenzip), 'x', '-so', str(component), MEDIA['runtime']['member']],
                       stdout=output, check=True, timeout=180)
    verify(runtime, MEDIA['runtime'])
    for key in ('main_disk', 'nand'):
        extract_member(runtime, work / MEDIA[key]['member'], MEDIA[key])
    base, nand = work / 'sdk.raw', work / 'nand.raw'
    for key, target in [('main_disk', base), ('nand', nand)]:
        subprocess.run([str(args.qemu_img), 'convert', '-f', 'qcow2', '-O', 'raw',
                        str(work / MEDIA[key]['member']), str(target)], check=True, timeout=240)
    layout = partitions(base)
    kernel = work / 'zImage-2.6.32.26-qemu'
    extract_slice(nand, kernel, MEDIA['kernel'], 'offset_in_raw_nand')
    print('2/6 Extracting kernel and graphics adaptation / 提取内核与图形适配', flush=True)
    sdk_root = work / 'sdk-root.ext4'
    copy_range(base, sdk_root, layout[1][1], layout[1][2], sparse=True)
    make_overlay(sdk_root, work, args.debugfs)
    print('3/6 Restoring pinned PR1.3 rootfs / 还原 PR1.3 根文件系统', flush=True)
    payload = work / 'rootfs.payload'
    extract_slice(args.firmware, payload, MEDIA['firmware']['rootfs_payload'])
    retail = work / 'retail-rootfs.ext4'
    decompress_rootfs(payload, work / 'rootfs.stream', retail, args.lzo_library)
    derived = work / 'pr1.3-rootfs-qemu-rescue.ext4'
    subprocess.run(['/bin/cp', '-c', str(retail), str(derived)], check=True)
    shutil.copyfile(ROOT / 'scripts/harmattan-qemu/preinit-rescue.sh', work / 'preinit')
    shutil.copyfile(ROOT / 'scripts/harmattan-qemu/apply-pr13-ui-overlay.sh', work / 'apply.sh')
    (work / 'prepare-init').write_text(PREPARE_INIT)
    commands = ['rm /sbin/preinit', 'write preinit /sbin/preinit',
                'set_inode_field /sbin/preinit mode 0100755',
                'write prepare-init /harmattan-prepare.sh',
                'set_inode_field /harmattan-prepare.sh mode 0100755',
                'write apply.sh /harmattan-apply.sh',
                'write overlay.tar.gz /harmattan-overlay.tar.gz',
                'set_inode_field / mode 040755']
    debugfs(args.debugfs, derived, commands, work / 'rootfs-edit.log', write=True, cwd=work)
    print('4/6 Assembling a new sparse disk / 组装新的稀疏磁盘', flush=True)
    disk = work / 'harmattan-pr1.3.raw'
    with disk.open('xb') as output:
        output.truncate(DISK_BYTES)
    copy_range(base, disk, 0, 512)
    for index in (0, 2):
        _, offset, length = layout[index]
        copy_range(base, disk, offset, length, target_offset=offset, sparse=True)
    copy_range(derived, disk, 0, derived.stat().st_size, target_offset=layout[1][1], sparse=True)
    print('5/6 Applying adaptation inside the derived guest / 在派生客体内应用适配', flush=True)
    prepare_boot(args.qemu_system_arm, disk, kernel, work)
    print('6/6 Recording output identities / 记录产物身份', flush=True)
    # Export the completed root for source-build linking; disk is already stopped.
    with derived.open('wb') as output:
        output.truncate(MEDIA['retail_rootfs']['bytes'])
    copy_range(disk, derived, layout[1][1], MEDIA['retail_rootfs']['bytes'], sparse=True)
    record = {'schema_version': 1, 'media': {key: MEDIA[key]['sha256'] for key in ('sdk', 'firmware')},
              'script_sha256': sha(Path(__file__)),
              'recipe_files': {str(p.relative_to(ROOT)): sha(p) for p in [
                  ROOT / 'docs/guest-media.json', ROOT / 'docs/inputs.json',
                  *(ROOT / 'scripts/harmattan-qemu' / name for name in (
                      'preinit-rescue.sh', 'xorg-pr13-qemu.conf', 'start-pr13-qemu-ui.sh',
                      'invoker-direct-qemu.sh', 'apply-pr13-ui-overlay.sh'))]},
              'qemu_sha256': sha(args.qemu_system_arm),
              'outputs': {p.name: {'bytes': p.stat().st_size, 'sha256': sha(p)} for p in (disk, kernel, derived)},
              'scope': 'Exact media extraction and in-guest adaptation complete; run the app diagnostic separately.'}
    (work / 'prepared-inputs.json').write_text(json.dumps(record, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk-exe', type=Path, required=True)
    parser.add_argument('--firmware', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='New directory; existing paths are refused')
    parser.add_argument('--sevenzip', type=Path, required=True)
    parser.add_argument('--debugfs', type=Path, required=True)
    parser.add_argument('--lzo-library', type=Path, required=True)
    parser.add_argument('--qemu-img', type=Path, required=True)
    parser.add_argument('--qemu-system-arm', type=Path, required=True, help='Harmattan native QEMU from the app')
    args = parser.parse_args()
    if args.output.expanduser().is_symlink():
        raise ValueError('Output is a symlink / 输出路径是符号链接，拒绝覆盖')
    for name, value in vars(args).items():
        setattr(args, name, value.expanduser().resolve())
    if args.output.exists():
        raise ValueError('Output already exists / 输出目录已存在，拒绝覆盖')
    for name in ('sevenzip', 'debugfs', 'qemu_img', 'qemu_system_arm'):
        if not getattr(args, name).is_file() or not os.access(getattr(args, name), os.X_OK):
            raise ValueError(f'Missing executable: {name}')
    if not args.lzo_library.is_file():
        raise ValueError('Missing liblzo2')
    if not (args.qemu_system_arm.parent.parent / 'Frameworks/libEGL.1.dylib').is_file():
        raise ValueError('Use qemu-system-arm inside the complete prebuilt application')
    print('Checking complete original media / 校验完整原始材料', flush=True)
    verify(args.sdk_exe, MEDIA['sdk'])
    verify(args.firmware, MEDIA['firmware'])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Neutral, short staging names also keep debugfs and QEMU option parsing simple.
    work = Path(tempfile.mkdtemp(prefix='harmattan-prepare-', dir='/private/tmp'))
    try:
        prepare(args, work)
        # Refuse cross-volume moves instead of unexpectedly copying many GiB.
        if args.output.exists():
            raise ValueError('Output appeared during preparation')
        work.rename(args.output)
    except BaseException:
        print(f'Incomplete workspace retained / 保留失败现场: {work}', flush=True)
        raise
    print(f'Prepared / 已准备: {args.output}\nRun the application diagnostic before relying on this disk.', flush=True)


if __name__ == '__main__':
    main()
