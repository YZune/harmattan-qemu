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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--guest', action='store_true', help='also check guest files and helper tools')
    args = parser.parse_args()
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
