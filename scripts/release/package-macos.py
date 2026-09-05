#!/usr/bin/env python3
"""Assemble an explicit, relocatable macOS runtime and preserved source kit."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / 'scripts/harmattan-qemu'
SPEC = importlib.util.spec_from_file_location('prebuilt', SCRIPTS / 'prebuilt-helpers.py')
prebuilt = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prebuilt)
# Internal controller runtime, not a general-purpose Python installation.
EXTENSIONS = set('array binascii fcntl grp math select resource unicodedata zlib '
                 '_bisect _blake2 _bz2 _datetime _heapq _json _md5 _opcode _pickle '
                 '_posixsubprocess _random _sha1 _sha2 _sha3 _socket _struct _ctypes'.split())
RELEASE_HELPERS = ('matrices', 'handoff', 'orientation', 'keyboard')
LICENSE_NAMES = re.compile(r'^(COPYING|LICENSE|LICENCE|NOTICE|COPYRIGHT|BSD|GPL|LGPL|MIT)([._-].*)?$', re.I)


def call(*args, **kwargs):
    return subprocess.check_output([str(a) for a in args], text=True, **kwargs).strip()


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def copy(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    target.chmod(source.stat().st_mode & 0o777)


def dependencies(path):
    return [line.strip().split(' (')[0] for line in call('otool', '-L', path).splitlines()[1:]]


def system_library(name):
    return name.startswith(('/usr/lib/', '/System/Library/'))


def minimum_macos(load_commands):
    versions = re.findall(r'^\s+minos (\d+)\.(\d+)(?:\.\d+)?$', load_commands, re.M)
    for command in re.split(r'Load command \d+', load_commands):
        if 'cmd LC_VERSION_MIN_MACOSX\n' in command:
            versions += re.findall(r'^\s+version (\d+)\.(\d+)(?:\.\d+)?$', command, re.M)
    return max((tuple(map(int, version)) for version in versions), default=(0, 0))


class Libraries:
    def __init__(self, contents, search):
        self.contents = contents
        self.frameworks = contents / 'Frameworks'
        self.search = search
        self.copied = {}
        self.origins = {}

    def resolve(self, name, owner):
        if name.startswith('@loader_path/'):
            candidates = [owner.parent / name[len('@loader_path/'):]]
        elif name.startswith('@rpath/'):
            candidates = [root / Path(name).name for root in self.search]
        elif name.startswith('/'):
            candidates = [Path(name)]
            # Python is staged under DESTDIR with a neutral configure prefix.
            if name.startswith('/opt/harmattan-python/lib/'):
                candidates += [root / Path(name).name for root in self.search]
        else:
            candidates = [owner.parent / name] + [root / name for root in self.search]
        for candidate in candidates:
            if candidate.is_file():
                return candidate.resolve()
        raise ValueError(f'Unresolved non-system dependency: {name}')

    def bundle(self, original, target=None):
        original = original.resolve()
        if original in self.copied:
            return self.copied[original]
        target = target or self.frameworks / original.name
        if target in self.origins and self.origins[target] != original:
            raise ValueError(f'Conflicting library basename: {target.name}')
        copy(original, target)
        self.copied[original] = target
        self.origins[target] = original
        # Edits invalidate the old signature. Sign only after the graph is final.
        subprocess.run(['codesign', '--remove-signature', str(target)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        if target.suffix == '.dylib':
            call('install_name_tool', '-id', '@rpath/' + target.name, target)
        for name in dependencies(original):
            if system_library(name):
                continue
            dependency = self.resolve(name, original)
            if dependency == original:  # LC_ID_DYLIB, not a dependency.
                continue
            bundled = self.bundle(dependency)
            relative = os.path.relpath(bundled, target.parent)
            call('install_name_tool', '-change', name, '@loader_path/' + relative, target)
        return target

    def audit(self):
        inventory = []
        minimum = (14, 0)
        for original, target in sorted(self.copied.items(), key=lambda pair: str(pair[1])):
            info = call('otool', '-l', target)
            minimum = max(minimum, minimum_macos(info))
            deps = dependencies(target)
            for name in deps:
                if system_library(name):
                    continue
                if name == '@rpath/' + target.name and target.suffix == '.dylib':
                    continue
                if not name.startswith('@loader_path/'):
                    raise ValueError(f'Non-relocatable load command: {target.name}: {name}')
                linked = (target.parent / name[len('@loader_path/'):]).resolve()
                if not linked.is_relative_to(self.contents.resolve()) or not linked.is_file():
                    raise ValueError(f'Bundle dependency escapes or is missing: {name}')
            if str(Path.home()).encode() in target.read_bytes():
                raise ValueError(f'Personal build path in binary: {target.name}; rebuild in a neutral workspace')
            call('codesign', '--force', '--sign', '-', target, stderr=subprocess.DEVNULL)
            inventory.append({'path': str(target.relative_to(self.contents)),
                              'sha256': sha(target), 'loads': deps})
        return '.'.join(map(str, minimum)), inventory


def project_files():
    if (ROOT / '.git').exists():
        listed = call('git', '-C', ROOT, 'ls-files', '-z', '--cached', '--others', '--exclude-standard').split('\0')
    else:
        listed = []
        ignored = {'downloads', 'extracted', 'artifacts', '.git', '.venv', '__pycache__'}
        for directory, children, names in os.walk(ROOT):
            children[:] = [name for name in children if name not in ignored]
            listed += [str((Path(directory) / name).relative_to(ROOT)) for name in names]
    return [Path(name) for name in sorted(set(listed)) if name and (ROOT / name).is_file()]


def helpers(destination, work):
    env = os.environ.copy()
    env.pop('HARMATTAN_PREBUILT_HELPERS', None)
    env['HARMATTAN_PORT_WORKSPACE'] = str(work)
    destination.mkdir(parents=True)
    manifest = {'schema_version': 1, 'helpers': {}}
    source_names = sorted(path.name for path in SCRIPTS.iterdir()
                          if path.suffix in ('.c', '.S') or path.name.startswith('build-') and path.suffix == '.sh')
    sources = {name: sha(SCRIPTS / name) for name in source_names}
    for name in RELEASE_HELPERS:
        relative, _ = prebuilt.HELPERS[name]
        if name in ('matrices', 'splash', 'handoff'):
            command = ['sh', str(SCRIPTS / 'build-compositor-guest.sh')]
            if name != 'matrices': command.append('--' + name)
        else:
            script = 'build-orientation-guest.sh' if name == 'orientation' else 'build-keyboard-probe.sh'
            command = ['sh', str(SCRIPTS / script)]
        subprocess.run(command, env=env, check=True, stdout=subprocess.DEVNULL)
        target = destination / relative
        copy(work / relative, target)
        manifest['helpers'][name] = {'sha256': sha(target), 'sources': sources}
    (destination / 'helpers.json').write_text(json.dumps(manifest, indent=2) + '\n')
    for name in RELEASE_HELPERS:
        prebuilt.verify(destination, name)


def preserve_sources(kit, licenses, cache, libraries, qemu, dgles, python_source):
    records = json.loads((ROOT / 'docs/release-sources.json').read_text())['sources']
    records += [dict(item, filename=Path(item['path']).name) for item in
                json.loads((ROOT / 'docs/inputs.json').read_text())['inputs'] if item['group'] == 'source']
    for source in records:
        path = cache / source['filename']
        if not path.is_file() or sha(path) != source['sha256']:
            raise ValueError(f'Missing or mismatched source archive: {source["filename"]}')
        copy(path, kit / 'project/downloads/tools' / source['filename'])
        if tarfile.is_tarfile(path):
            with tarfile.open(path) as archive:
                for member in archive:
                    # Preserve upstream notices without extracting arbitrary paths.
                    if member.isfile() and member.size < 2**20 and LICENSE_NAMES.match(Path(member.name).name):
                        safe = Path(member.name)
                        if safe.is_absolute() or '..' in safe.parts:
                            raise ValueError('Unsafe source notice path')
                        target = licenses / source['id'] / safe
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_bytes(archive.extractfile(member).read())
    # Installed formula and source inputs preserve the modifications to bottles.
    recipes = kit / 'build-recipes/homebrew'
    for original in libraries.copied:
        parts = original.parts
        if '/opt/homebrew/Cellar/' not in str(original):
            continue
        index = parts.index('Cellar')
        name, version = parts[index + 1:index + 3]
        record = next((r for r in records if r['id'] == name), None)
        if not record or record.get('version') != version:
            raise ValueError(f'No corresponding pinned source for bundled library: {name} {version}')
        cellar = Path(*parts[:index + 3])
        for recipe in (cellar / '.brew').glob('*.rb'):
            copy(recipe, recipes / recipe.name)
        for notice in cellar.iterdir():
            if notice.is_file() and LICENSE_NAMES.match(notice.name):
                copy(notice, licenses / name / ('homebrew-' + notice.name))
    patch = cache / 'glib-hardcoded-paths.diff'
    copy(patch, recipes / 'Patches/glib/hardcoded-paths.diff')
    # Also preserve the exact patched translation units and generated configs.
    # Build trees are local evidence only; project scripts remain the maintained source.
    for label, source, excludes in (
        ('qemu-patched', qemu, {'build-arm64-interaction', '.git', '__pycache__'}),
        ('dgles-patched', dgles, {'objs-arm64', '.git', '__pycache__'}),
    ):
        target = kit / 'prepared-source' / label
        shutil.copytree(source, target, ignore=shutil.ignore_patterns(*excludes, '*.pyc', '*.o', '*.dylib', '*.a'), symlinks=True)
    copy(python_source / 'config.log', kit / 'build-recipes/python-config.log')
    copy(qemu / 'build-arm64-interaction/config-host.mak', kit / 'build-recipes/qemu-config-host.mak')
    for name in ('intro-buildoptions.json', 'intro-dependencies.json', 'intro-compilers.json'):
        copy(qemu / 'build-arm64-interaction/meson-info' / name, kit / 'build-recipes' / name)
    # Build logs/configuration must use anonymous, portable source-kit locations.
    for path in (kit / 'build-recipes').rglob('*'):
        if path.is_file():
            data = path.read_text()
            data = data.replace(str(ROOT), '${PROJECT_ROOT}').replace(str(Path.home()), '${BUILD_HOME}')
            data = data.replace(str(qemu), '${QEMU_SOURCE}').replace(str(dgles), '${DGLES_SOURCE}')
            path.write_text(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qemu-source', type=Path, required=True)
    parser.add_argument('--dgles-source', type=Path, required=True, help='gles-libs-1.4.2 root')
    parser.add_argument('--python-work', type=Path, required=True)
    parser.add_argument('--helper-work', type=Path, required=True)
    parser.add_argument('--cache', type=Path, default=ROOT / 'downloads/tools')
    parser.add_argument('--output', type=Path, required=True, help='new output directory')
    parser.add_argument('--version', default='0.1.0-preview.1')
    args = parser.parse_args()
    if sys.version_info < (3, 12) or sys.platform != 'darwin':
        parser.error('Package on native ARM64 macOS with Python 3.12+')
    if call('uname', '-m') != 'arm64': parser.error('Use native ARM64')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    app = output / 'Harmattan QEMU.app'
    contents = app / 'Contents'
    project = contents / 'Resources/project'
    kit = output / 'harmattan-qemu-sources'
    files = project_files()
    for relative in files:
        copy(ROOT / relative, kit / 'project' / relative)
        if relative.parts[0] in ('scripts', 'ports', 'LICENSES') or relative.name in ('LICENSE', 'NOTICE'):
            copy(ROOT / relative, project / relative)
    # Never copy an existing local .app, its artwork or linked guest files.
    python_prefix = args.python_work / 'stage/opt/harmattan-python'
    stdlib = python_prefix / 'lib/python3.12'
    bundled_stdlib = contents / 'Resources/python/lib/python3.12'
    shutil.copytree(stdlib, bundled_stdlib,
                    ignore=shutil.ignore_patterns('site-packages', '__pycache__', 'test', 'tests',
                                                 'idlelib', 'tkinter', 'turtledemo', 'ensurepip',
                                                 'config-*', '*.pyc', 'lib-dynload', '*.a'))
    libraries = Libraries(contents, [args.dgles_source / 'dgles2/objs-arm64', python_prefix / 'lib'])
    build = args.qemu_source / 'build-arm64-interaction'
    for name in ('qemu-system-arm', 'qemu-img'):
        libraries.bundle(build / name, contents / 'MacOS' / name)
    libraries.bundle(python_prefix / 'bin/python3.12', contents / 'MacOS/python3')
    for extension in (stdlib / 'lib-dynload').glob('*.so'):
        if extension.name.split('.')[0] in EXTENSIONS:
            libraries.bundle(extension, bundled_stdlib / 'lib-dynload' / extension.name)
    for name in ('libEGL', 'libGLES_CM', 'libGLESv2'):
        target = libraries.bundle(args.dgles_source / 'dgles2/objs-arm64' / (name + '.dylib'))
        for alias in ((name + '.dylib'), (name + '.1.dylib') if name == 'libEGL' else target.name):
            path = contents / 'Frameworks' / alias
            if not path.exists(): path.symlink_to(target.name)
    helpers(contents / 'Resources/helpers', args.helper_work)
    licenses = contents / 'Resources/licenses'
    preserve_sources(kit, licenses, args.cache, libraries, args.qemu_source, args.dgles_source,
                     args.python_work / 'Python-3.12.14')
    launcher = contents / 'MacOS/harmattan'
    call('clang', '-arch', 'arm64', '-mmacosx-version-min=14.0', '-O2', '-fobjc-arc',
         '-framework', 'Cocoa', ROOT / 'scripts/release/launcher.m', '-o', launcher)
    call('codesign', '--force', '--sign', '-', launcher, stderr=subprocess.DEVNULL)
    minimum, inventory = libraries.audit()
    plist = {'CFBundleName': 'Harmattan QEMU', 'CFBundleDisplayName': 'Harmattan QEMU',
             'CFBundleIdentifier': 'org.harmattan-qemu.preview', 'CFBundleExecutable': 'harmattan',
             'CFBundlePackageType': 'APPL', 'CFBundleShortVersionString': args.version.split('-')[0],
             'HarmattanReleaseVersion': args.version,
             'CFBundleVersion': '1', 'NSHighResolutionCapable': True,
             'LSMinimumSystemVersion': minimum, 'LSArchitecturePriority': ['arm64']}
    (contents / 'Info.plist').write_bytes(plistlib.dumps(plist))
    manifest = {'schema_version': 1, 'version': args.version, 'minimum_macos': minimum,
                'source_commit': call('git', '-C', ROOT, 'rev-parse', 'HEAD') if (ROOT / '.git').exists() else None,
                'architecture': 'arm64', 'python': '3.12.14', 'qemu': '9.1.3',
                'signing': 'ad-hoc; not Developer ID signed or notarized',
                'requires': 'user-supplied prepared guest raw disk and pinned kernel; APFS',
                'excluded': ['guest disk', 'guest kernel', 'guest link libraries', 'SDK', 'Livven artwork'],
                'mach_o': inventory}
    (contents / 'Resources/runtime-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    for name in ('releases.md', 'releases.zh-CN.md'):
        label = 'README' + ('.zh-CN' if '.zh-CN' in name else '') + '.md'
        guide = (ROOT / 'docs' / name).read_text().replace('(releases.zh-CN.md)', '(README.zh-CN.md)').replace('(releases.md)', '(README.md)')
        (output / label).write_text(guide)
        (kit / label).write_text(guide)
    copy(ROOT / 'docs/THIRD_PARTY_NOTICES.md', contents / 'Resources/THIRD_PARTY_NOTICES.md')
    copy(ROOT / 'docs/THIRD_PARTY_NOTICES.zh-CN.md', contents / 'Resources/THIRD_PARTY_NOTICES.zh-CN.md')
    shutil.copytree(licenses, kit / 'third-party-licenses')
    call('codesign', '--force', '--sign', '-', app, stderr=subprocess.DEVNULL)
    call('codesign', '--verify', '--deep', '--strict', app)
    print(f'Bundle assembled: {app}\nMinimum macOS from load commands: {minimum}', flush=True)
    print('Run relocation and guest checks before making release archives.', flush=True)


if __name__ == '__main__':
    main()
