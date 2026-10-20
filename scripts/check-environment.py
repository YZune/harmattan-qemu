#!/usr/bin/env python3
"""Read-only prerequisite check; never downloads or modifies guest inputs."""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def linux_build_check():
    """Discover source-build inputs without compiling or opening guest files."""
    failed = []

    def report(name, ok, detail):
        print(f'{"OK" if ok else "MISSING"}: {name}: {detail}')
        if not ok:
            failed.append(name)

    report('Linux build host', (platform.system(), platform.machine()) == ('Linux', 'x86_64'),
           f'{platform.system()} {platform.machine()} (experimental Linux x86_64 path)')
    report('running Python', sys.version_info >= (3, 12), platform.python_version())
    search_path = os.environ.get('PATH')
    if search_path is None:
        # The builders run under sh, whose default PATH can differ from Python's.
        # This executes only the shell's printf builtin, not a selected tool.
        try:
            search_path = subprocess.run(['sh', '-c', 'printf "%s" "$PATH"'],
                                         check=True, capture_output=True, text=True,
                                         timeout=5).stdout
        except (OSError, subprocess.SubprocessError) as error:
            report('shell search path', False, str(error))
            return 1

    def discover(name, selected, path=search_path):
        # An explicitly empty shell PATH searches the current directory.
        found = shutil.which(selected, path=path or os.curdir)
        report(name, found is not None, f'{selected!r}' + (f' -> {found}' if found else ''))
        return found

    for name in ('sh', 'git', 'make', 'tar', 'shasum', 'file'):
        discover(name, name)
    discover('DGLES compiler (HARMATTAN_CC)', os.environ.get('HARMATTAN_CC') or 'cc')
    ninja = discover('Ninja (HARMATTAN_NINJA)', os.environ.get('HARMATTAN_NINJA') or 'ninja')
    # build-arm64-port.sh prepends the resolved Ninja directory before selecting
    # Python and pkg-config. Keep this local; never change the caller's environment.
    qemu_path = f'{os.path.dirname(ninja) or os.curdir}:{search_path}' if ninja else search_path
    discover('QEMU Python (HARMATTAN_PYTHON)',
             os.environ.get('HARMATTAN_PYTHON') or 'python3', qemu_path)
    pkg_config = discover('QEMU pkg-config', 'pkg-config', qemu_path)
    for package in ('glib-2.0', 'pixman-1', 'slirp'):
        detail = 'pkg-config development dependency'
        available = False
        if pkg_config is not None:
            try:
                available = subprocess.run(
                    [pkg_config, '--exists', package], check=False,
                    env={**os.environ, 'PATH': qemu_path}, timeout=5,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
            except (OSError, subprocess.SubprocessError) as error:
                detail += f' ({type(error).__name__}: {error})'
        report(package, available, detail)

    manifest = json.loads((ROOT / 'docs/inputs.json').read_text())
    for item in manifest['inputs']:
        if item['group'] != 'source':
            continue
        value = os.environ.get(item.get('environment', '')) or str(ROOT / item['path'])
        try:
            exists, detail = Path(value).is_file(), value
        except OSError as error:
            exists, detail = False, f'{value} ({type(error).__name__}: {error})'
        report(f'source archive {item["id"]}', exists, detail)
    print('Discovery only: runs bounded pkg-config queries and, if needed, a shell PATH query. '
          'Missing source archives are expected before Linux guide step 2. '
          'Build scripts verify their hashes. This does not verify the selected Python version, '
          'QEMU compiler capabilities, OSMesa linking/loading, graphics, free space or guest readiness. '
          'HARMATTAN_CC selects DGLES only; continue with docs/linux.md for the build and smoke checks.')
    return 1 if failed else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--guest', action='store_true', help='also check guest files and helper tools')
    parser.add_argument('--linux-build', action='store_true',
                        help='discover experimental Linux source-build prerequisites, without guest checks')
    args = parser.parse_args(argv)
    if args.linux_build:
        if args.guest:
            parser.error('--linux-build cannot be combined with --guest; see docs/linux.md for guest preparation')
        return linux_build_check()
    failed = []

    def report(name, ok, detail):
        print(f'{"OK" if ok else "MISSING"}: {name}: {detail}')
        if not ok:
            failed.append(name)

    report('native host', platform.system() == 'Darwin' and platform.machine() == 'arm64',
           f'{platform.system()} {platform.machine()} (full runtime requires Apple Silicon macOS)')
    report('Python', sys.version_info >= (3, 12), platform.python_version())
    for name, override in [('clang', 'HARMATTAN_CC'), ('ninja', 'HARMATTAN_NINJA'),
                           ('pkg-config', None)]:
        selected = os.environ.get(override, name) if override else name
        found = shutil.which(selected)
        report(name, found is not None, found or selected)
    for package in ('glib-2.0', 'pixman-1', 'slirp'):
        available = shutil.which('pkg-config') is not None and subprocess.run(
            ['pkg-config', '--exists', package], check=False).returncode == 0
        report(package, available, 'pkg-config development dependency')
    manifest = json.loads((ROOT / 'docs/inputs.json').read_text())
    for item in manifest['inputs']:
        if item['group'] != 'source' and not args.guest:
            continue
        value = os.environ.get(item.get('environment', ''), str(ROOT / item['path']))
        exists = Path(value).is_file()
        if item.get('optional'):
            print(f'OPTIONAL: {item["id"]}: {"present" if exists else "absent"}')
        else:
            report(item['id'], exists, value)
    if args.guest:
        for name, key in [('clang', 'HARMATTAN_ARMEL_CLANG'), ('debugfs', 'HARMATTAN_DEBUGFS')]:
            value = os.environ.get(key, name)
            found = shutil.which(value)
            report(key, found is not None, found or value)
    print('Checks file presence/tool discovery only; build scripts verify pinned hashes. '
          'APFS cloning, graphics execution, ARM/lld capability, and guest contents require runtime validation.')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
