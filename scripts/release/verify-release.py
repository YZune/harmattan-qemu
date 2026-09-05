#!/usr/bin/env python3
"""Audit assembled release contents and optionally create checksummed archives."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('packager', Path(__file__).with_name('package-macos.py'))
packager = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(packager)


def verify(directory):
    app = directory / 'Harmattan QEMU.app'
    contents = app / 'Contents'
    kit = directory / 'harmattan-qemu-sources'
    manifest = json.loads((contents / 'Resources/runtime-manifest.json').read_text())
    known_macho = {item['path']: item for item in manifest['mach_o']}
    for relative in packager.project_files():
        if packager.sha(ROOT / relative) != packager.sha(kit / 'project' / relative):
            raise ValueError(f'Source kit differs from reviewed worktree: {relative}')
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)
    for name in packager.RELEASE_HELPERS:
        packager.prebuilt.verify(contents / 'Resources/helpers', name,
                                 contents / 'Resources/project/scripts/harmattan-qemu')
    known_helpers = {packager.prebuilt.HELPERS[name][0] for name in packager.RELEASE_HELPERS}
    for path in contents.rglob('*'):
        relative = str(path.relative_to(contents))
        if path.is_symlink():
            if not path.resolve().is_relative_to(contents) or not path.resolve().is_file():
                raise ValueError(f'Uncontained bundle symlink: {relative}')
            continue
        if not path.is_file(): continue
        data = path.read_bytes()
        if str(Path.home()).encode() in data:
            raise ValueError(f'Personal home path in app: {relative}')
        if path.suffix.lower() in ('.png', '.jpg', '.psd', '.raw', '.ext4', '.qcow2', '.iso', '.dmg'):
            raise ValueError(f'Unexpected artwork or guest input in app: {relative}')
        if data[:4] == b'\x7fELF':
            if not relative.startswith('Resources/helpers/') or relative.removeprefix('Resources/helpers/') not in known_helpers:
                raise ValueError(f'Unexpected guest executable: {relative}')
        if data[:4] == b'\xcf\xfa\xed\xfe':
            if relative != 'MacOS/harmattan':
                if relative not in known_macho or packager.sha(path) != known_macho[relative]['sha256']:
                    raise ValueError(f'Unknown or changed Mach-O: {relative}')
            for load in packager.dependencies(path):
                if packager.system_library(load): continue
                if load == '@rpath/' + path.name and path.suffix == '.dylib': continue
                if not load.startswith('@loader_path/'):
                    raise ValueError(f'External load command: {relative}: {load}')
                target = (path.parent / load.removeprefix('@loader_path/')).resolve()
                if not target.is_relative_to(contents) or not target.is_file():
                    raise ValueError(f'Unresolved bundled dependency: {relative}: {load}')
    sources = json.loads((ROOT / 'docs/release-sources.json').read_text())['sources']
    sources += [dict(item, filename=Path(item['path']).name) for item in
                json.loads((ROOT / 'docs/inputs.json').read_text())['inputs'] if item['group'] == 'source']
    for item in sources:
        if packager.sha(kit / 'project/downloads/tools' / item['filename']) != item['sha256']:
            raise ValueError(f'Source archive mismatch: {item["id"]}')
    for path in kit.rglob('*'):
        if path.is_symlink() and not path.resolve().is_relative_to(kit):
            raise ValueError(f'Source-kit symlink escapes: {path.relative_to(kit)}')
    print(f'PASS: signatures, contained dependencies, {len(known_macho)} recorded Mach-O files, '
          f'{len(known_helpers)} helper binaries, source equality and {len(sources)} preserved source inputs.')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--archive', action='store_true')
    args = parser.parse_args()
    directory = args.directory.resolve()
    manifest = verify(directory)
    if args.archive:
        version = manifest['version']
        binary = directory / f'Harmattan-QEMU-{version}-macos-arm64.zip'
        source = directory / f'Harmattan-QEMU-{version}-sources.tar.gz'
        checksums = directory / 'SHA256SUMS'
        if any(path.exists() for path in (binary, source, checksums)):
            raise ValueError('Refusing to overwrite release archives/checksums')
        subprocess.run(['/usr/bin/ditto', '-c', '-k', '--norsrc', '--noextattr', '--keepParent',
                        str(directory / 'Harmattan QEMU.app'), str(binary)], check=True)
        with tarfile.open(source, 'w:gz', compresslevel=6) as archive:
            def anonymous(member):
                member.uid = member.gid = 0
                member.uname = member.gname = ''
                return member
            archive.add(directory / 'harmattan-qemu-sources', arcname='harmattan-qemu-sources', filter=anonymous)
        files = [binary, source, directory / 'README.md', directory / 'README.zh-CN.md']
        checksums.write_text(''.join(f'{packager.sha(path)}  {path.name}\n' for path in files))
        print(checksums.read_text(), end='')


if __name__ == '__main__':
    main()
