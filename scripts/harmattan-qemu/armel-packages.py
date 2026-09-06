#!/usr/bin/env python3
"""Inspect bounded historical ARMEL Debian packages without extracting files."""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import tarfile


MAX_PACKAGE = 64 * 1024 ** 2


def members(data):
    if not data.startswith(b'!<arch>\n'):
        raise ValueError('not a Debian ar archive')
    result, position = {}, 8
    while position < len(data):
        header = data[position:position + 60]
        if len(header) != 60 or header[58:] != b'`\n':
            raise ValueError('truncated ar header')
        name = header[:16].decode('ascii').strip().removesuffix('/')
        try:
            length = int(header[48:58])
        except ValueError as exc:
            raise ValueError('invalid ar member length') from exc
        start, end = position + 60, position + 60 + length
        if length < 0 or end > len(data) or name in result or len(result) >= 8:
            raise ValueError('duplicate or unbounded ar member')
        result[name] = data[start:end]
        position = end + length % 2
    if position != len(data):
        raise ValueError('truncated ar padding')
    return result


def control_fields(text):
    result, previous = {}, None
    for line in text.splitlines():
        if line.startswith((' ', '\t')) and previous:
            result[previous] += '\n' + line
        elif line:
            key, separator, value = line.partition(':')
            if not separator or key in result or not re.fullmatch(r'[A-Za-z][A-Za-z0-9-]*', key):
                raise ValueError('invalid or duplicate control field')
            result[key] = value.strip()
            previous = key
    for name in ('Package', 'Version', 'Architecture'):
        if not result.get(name):
            raise ValueError('missing package identity')
    if not re.fullmatch(r'[a-z0-9][a-z0-9+.-]+', result['Package']):
        raise ValueError('invalid package name')
    if not re.fullmatch(r'[A-Za-z0-9.+:~_-]+', result['Version']):
        raise ValueError('invalid package version')
    if result['Architecture'] not in ('armel', 'all'):
        raise ValueError('requires Harmattan armel/all packages, not another CPU ABI')
    return result


def inspect_bytes(data):
    if not 0 < len(data) <= MAX_PACKAGE:
        raise ValueError('package exceeds the 64 MiB bound')
    archive = members(data)
    if archive.get('debian-binary') != b'2.0\n':
        raise ValueError('unsupported Debian package version')
    required = {'debian-binary', 'control.tar.gz', 'data.tar.gz'}
    if not required <= set(archive) or set(archive) - required - {'_x509sig'}:
        raise ValueError('requires the historical control.tar.gz/data.tar.gz layout')
    if len(archive.get('_x509sig', b'')) > 16384:
        raise ValueError('oversized historical signature member')
    files = {}
    with tarfile.open(fileobj=io.BytesIO(archive['control.tar.gz']), mode='r|gz') as tar:
        for index, item in enumerate(tar):
            if index >= 64 or item.size > 1024 ** 2:
                raise ValueError('oversized control archive')
            name = str(PurePosixPath(item.name))
            if name == '.' and item.isdir():
                continue
            if not item.isfile() or '/' in name or name in files or name in ('', '..'):
                raise ValueError('unsafe or duplicate control member')
            files[name] = tar.extractfile(item).read(item.size + 1)
    fields = control_fields(files.get('control', b'').decode('utf-8'))
    scripts = {name: files[name].decode('utf-8') for name in ('preinst', 'postinst', 'prerm', 'postrm', 'config') if name in files}
    return {'package': fields['Package'], 'version': fields['Version'], 'architecture': fields['Architecture'],
            'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'sha1': hashlib.sha1(data).hexdigest(), 'control': fields, 'maintainer_scripts': scripts,
            'historical_signature_present': '_x509sig' in archive, 'signature_verified': False}


def inspect(path):
    path = Path(path)
    if not path.is_file() or not 0 < path.stat().st_size <= MAX_PACKAGE:
        raise ValueError('expected a regular Debian package of at most 64 MiB')
    return inspect_bytes(path.read_bytes())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('packages', nargs='+', type=Path)
    args = parser.parse_args()
    print(json.dumps([dict(filename=path.name, **inspect(path)) for path in args.packages], indent=2))
