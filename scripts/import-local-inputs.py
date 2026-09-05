#!/usr/bin/env python3
"""Import an explicit allowlist of local research inputs. Dry-run by default."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source_workspace', type=Path)
    parser.add_argument('--apply', action='store_true', help='copy validated inputs into ignored directories')
    args = parser.parse_args()
    if sys.version_info < (3, 12):
        parser.error('use Python 3.12 or newer; see docs/building.md for PATH selection')
    source = args.source_workspace.resolve(strict=True)
    if source == ROOT:
        parser.error('source and destination must differ')
    manifest = json.loads((ROOT / 'docs/inputs.json').read_text())
    plan = []
    for item in manifest['inputs']:
        relative = Path(item['path'])
        if relative.is_absolute() or '..' in relative.parts or relative.parts[0] not in ('downloads', 'extracted'):
            parser.error('manifest path is outside the input allowlist')
        src = source / relative
        dst = ROOT / relative
        if not src.is_file():
            if item.get('optional'):
                continue
            parser.error(f'missing source input: {relative}')
        if dst.exists() or dst.is_symlink():
            parser.error(f'refusing existing destination: {relative}')
        # Refuse an existing parent symlink that could redirect the import.
        if any(parent.is_symlink() for parent in dst.parents if parent != ROOT and ROOT in parent.parents):
            parser.error(f'destination parent is a symlink: {relative}')
        size = src.stat().st_size
        if size <= 0 or size > item.get('max_bytes', 2**31):
            parser.error(f'input size outside expected bounds: {relative}')
        expected = item.get('sha256')
        if expected and digest(src) != expected:
            parser.error(f'SHA-256 mismatch: {relative}')
        print(f'{"CLONE" if item.get("apfs_clone") else "COPY"}: {relative} ({size} bytes)')
        plan.append((item, src, dst, size))
    if not args.apply:
        print('Dry run; no files changed. Re-run with --apply to import this allowlist.')
        return
    for item, src, dst, size in plan:
        dst.parent.mkdir(parents=True, exist_ok=True)
        # Stage next to the destination, then create the final name exclusively.
        with tempfile.TemporaryDirectory(prefix='.input-', dir=dst.parent) as temporary:
            staged = Path(temporary) / 'input'
            if item.get('apfs_clone'):
                subprocess.run(['cp', '-c', str(src), str(staged)], check=True)
            else:
                shutil.copyfile(src, staged)
            if staged.stat().st_size != size or (item.get('sha256') and digest(staged) != item['sha256']):
                raise RuntimeError(f'copy verification failed: {item["path"]}')
            # link() fails atomically if the final name appeared during copying.
            dst.hardlink_to(staged)
    print(f'Imported {len(plan)} inputs. No Git operation performed. Guest disk contents were not audited.')


if __name__ == '__main__':
    main()
