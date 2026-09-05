#!/usr/bin/env python3
"""Download pinned release source inputs; existing mismatches are never replaced."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, default=ROOT / 'downloads/tools')
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    for source in json.loads((ROOT / 'docs/release-sources.json').read_text())['sources']:
        destination = args.cache / source['filename']
        if not destination.exists():
            if args.offline or not source.get('url'):
                raise SystemExit(f'Missing preserved source: {destination}; see docs/releases.md')
            with tempfile.TemporaryDirectory(prefix='.fetch-', dir=args.cache) as temporary:
                path = Path(temporary) / 'source'
                subprocess.run(['curl', '--fail', '--location', '--retry', '2', '--max-time', '180',
                                '--output', str(path), source['url']], check=True)
                if hashlib.sha256(path.read_bytes()).hexdigest() != source['sha256']:
                    raise SystemExit(f'Download SHA-256 mismatch: {source["id"]}')
                destination.hardlink_to(path)
        if hashlib.sha256(destination.read_bytes()).hexdigest() != source['sha256']:
            raise SystemExit(f'Cached SHA-256 mismatch: {source["id"]}')
        print(f'OK {source["id"]}', flush=True)


if __name__ == '__main__':
    main()
