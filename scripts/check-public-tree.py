#!/usr/bin/env python3
"""Check published source, reviewed screenshots, and local Markdown links."""
from pathlib import Path
import hashlib
import re
import subprocess
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_ROOTS = {'scripts', 'ports', 'docs', 'LICENSES', '.github'}
ALLOWED_FILES = {'README.md', 'README.zh-CN.md', 'CONTRIBUTING.md', 'CONTRIBUTING.zh-CN.md',
                 'AGENTS.md', 'AGENTS.zh-CN.md', 'LICENSE', 'NOTICE', '.gitignore', '.gitattributes'}
IGNORED = {'.git', 'downloads', 'extracted', 'artifacts', '.venv', '__pycache__'}
FORBIDDEN_SUFFIXES = {'.png', '.jpg', '.psd', '.raw', '.qcow2', '.ext4', '.bin', '.dmg',
                      '.iso', '.exe', '.dylib', '.so', '.zip', '.gz', '.xz', '.log', '.pyc'}
# Individually reviewed, unedited QMP screendumps; no general media exception.
SCREENSHOTS = {
    'docs/screenshots/home.png': 'dcc8eb1d087635acb377d40414cce762904840b26dca43dc777fbfbeb7204309',
    'docs/screenshots/calculator.png': 'ee39b240b6e1c71674d52f0bdf3376245c24ae5db24d991bdd0f628a7b3235d1',
    'docs/screenshots/notes-keyboard.png': '78b93cd37721d7b89bb322bbbc9efd419ed17729f75f5c3d40a72f2dfc7e7d17',
}


def main():
    if (ROOT / '.git').exists():
        names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
        files = [ROOT / name for name in names if name]
    else:
        files = [p for p in ROOT.rglob('*') if p.is_file()
                 and not any(part in IGNORED for part in p.relative_to(ROOT).parts)]
    errors = []
    token_pattern = re.compile(r'\b(?:' + 'gh' + r'[pousr]_[A-Za-z0-9]{30,}|' +
                               'github' + r'_pat_[A-Za-z0-9_]{40,})\b')
    for path in files:
        relative = path.relative_to(ROOT)
        if relative.parts[0] not in ALLOWED_ROOTS and str(relative) not in ALLOWED_FILES:
            errors.append(f'outside source allowlist: {relative}')
        if path.is_symlink() or path.stat().st_size > 2_000_000:
            errors.append(f'non-source or oversized file: {relative}')
            continue
        if str(relative) in SCREENSHOTS:
            if hashlib.sha256(path.read_bytes()).hexdigest() != SCREENSHOTS[str(relative)]:
                errors.append(f'screenshot differs from reviewed capture: {relative}')
            continue
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            errors.append(f'non-source file: {relative}')
            continue
        try:
            content = path.read_text(encoding='utf-8')
        except UnicodeError:
            errors.append(f'non-UTF8 file: {relative}')
            continue
        if '\0' in content or token_pattern.search(content) or re.search(r'/Users/[A-Za-z0-9_.-]+/', content):
            errors.append(f'binary, credential-shaped text, or private home path: {relative}')
        if path.suffix == '.md':
            text = re.sub(r'```.*?```', '', content, flags=re.S)
            for link in re.findall(r'\]\(([^)]+)\)', text):
                target = link.split(' ', 1)[0].strip('<>')
                parsed = urlsplit(target)
                if parsed.scheme or target.startswith('#') or not parsed.path:
                    continue
                resolved = (path.parent / unquote(parsed.path)).resolve()
                if not resolved.is_relative_to(ROOT) or not resolved.is_file():
                    errors.append(f'broken or external local link: {relative}: {target}')
            if path.name.endswith('.zh-CN.md'):
                counterpart = path.with_name(path.name.replace('.zh-CN.md', '.md'))
                if not counterpart.is_file():
                    errors.append(f'missing English counterpart: {relative}')
            elif '.github' not in relative.parts:
                counterpart = path.with_name(path.stem + '.zh-CN.md')
                if not counterpart.is_file():
                    errors.append(f'missing Chinese counterpart: {relative}')
    if not files:
        errors.append('no source files selected')
    for error in errors:
        print('FAIL:', error)
    print(f'Checked {len(files)} publication files; {len(errors)} errors. '
          'This bounded check supplements human review; it is not a complete secret/license audit.')
    return bool(errors)


if __name__ == '__main__':
    raise SystemExit(main())
