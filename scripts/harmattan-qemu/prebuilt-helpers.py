#!/usr/bin/env python3
"""Verify release helpers against their binary and corresponding source hashes."""
import hashlib
import json
import os
from pathlib import Path
import sys

HELPERS = {
    'matrices': ('compositor-guest/n00-compositor-matrices.so', 3),
    'splash': ('compositor-guest/n00-compositor-splash.so', 3),
    'handoff': ('compositor-guest/n00-compositor-handoff.so', 3),
    'orientation': ('orientation-guest/n00-orientation-provider', 2),
    'keyboard': ('keyboard-probe/keyboard-notes-read', 2),
}


def verify(root, name, scripts=None):
    scripts = scripts or Path(__file__).resolve().parent
    relative, elf_type = HELPERS[name]
    manifest = json.loads((root / 'helpers.json').read_text())
    if manifest.get('schema_version') != 1:
        raise ValueError('unsupported prebuilt helper manifest')
    record = manifest['helpers'][name]
    data = (root / relative).read_bytes()
    if (len(data) < 52 or data[:7] != b'\x7fELF\x01\x01\x01'
            or data[16:20] != bytes((elf_type, 0, 40, 0))):
        raise ValueError('prebuilt helper has the wrong ARM ELF ABI')
    if hashlib.sha256(data).hexdigest() != record['sha256']:
        raise ValueError('prebuilt helper SHA-256 mismatch')
    if not record.get('sources'):
        raise ValueError('prebuilt helper has no corresponding source records')
    for source, expected in record['sources'].items():
        if Path(source).name != source:
            raise ValueError('helper source path must be a filename')
        if hashlib.sha256((scripts / source).read_bytes()).hexdigest() != expected:
            raise ValueError(f'prebuilt helper source mismatch: {source}')
    return data


if __name__ == '__main__':
    verify(Path(os.environ['HARMATTAN_PREBUILT_HELPERS']), sys.argv[1])
