"""Prepare and validate the pinned original browser's software compositing entry."""
import hashlib
import os
from pathlib import Path
import re
import subprocess

ENTRIES = {
    'browser.desktop': ('/usr/share/applications/browser.desktop', '4efc2178f074de927851cd26f30dd94f'),
    'com.nokia.browser.service': ('/usr/share/dbus-1/services/com.nokia.browser.service', '5d51786364f868cc99ae9250d3d37f45'),
}


def adapt_entry(data, expected):
    if hashlib.md5(data).hexdigest() != expected or data.count(b'/usr/bin/grob') != 1:
        raise ValueError('original browser entry identity changed')
    return data.replace(b'/usr/bin/grob', b'/tmp/n00-ui-helpers/browser-launch-guest.sh')


def prepare(mode='original'):
    if mode not in ('original', 'basic'):
        raise ValueError('browser mode must be original or basic')
    scripts = Path(__file__).resolve().parent
    subprocess.run(['sh', str(scripts / 'build-browser-guest.sh')], check=True)
    work = Path(os.environ.get('HARMATTAN_PREBUILT_HELPERS') or
                os.environ.get('HARMATTAN_PORT_WORKSPACE', scripts.parents[1] / 'extracted/qemu-arm64-port'))
    data = (work / 'browser-guest/n00-browser.so').read_bytes()
    if (len(data) < 52 or data[:7] != b'\x7fELF\x01\x01\x01'
            or data[16:20] != b'\x03\x00\x28\x00'):
        raise ValueError('browser helper is not ARM ELF32 shared code')
    # Entry files are supplied by the guest at installation, never bundled.
    md5 = hashlib.md5(data).hexdigest()
    launch = (scripts / 'browser-launch-guest.sh').read_bytes()
    for placeholder, value in ((b'@HELPER_MD5@', md5), (b'@BROWSER_MODE@', mode)):
        if launch.count(placeholder) != 1:
            raise ValueError('browser launch placeholder changed')
        launch = launch.replace(placeholder, value.encode())
    payloads = {'n00-browser.so': data,
        'browser-launch-guest.sh': launch}
    return payloads, {'enabled': True, 'mode': mode,
        'javascript_policy': 'disabled' if mode == 'basic' else 'preserve-original', 'helper_md5': md5,
        'helper_sha256': hashlib.sha256(data).hexdigest(),
        'source_sha256': hashlib.sha256((scripts / 'browser-guest.c').read_bytes()).hexdigest(),
        'scope': 'pinned Grob software compositing and optional basic browsing through original preferences APIs; per-application entry'}


def install(serial, wait_line, upload, output, info):
    # Export only the two pinned guest entries as hexadecimal, then adapt them
    # on the host. The original on-disk files are preserved under tmpfs binds.
    serial.sendall(b"sh -eu <<'N00_BROWSER_ENTRY_EXPORT'\n"
        b"printf '\\nN00_BROWSER_ENTRIES_BEGIN\\n'\n"
        b"perl -e 'for(@ARGV){open(my $f,\"<\",$_) or die $!;local $/;my $v=<$f>;length($v)<16384 or die;print unpack(\"H*\",$v),\"\\n\"}' "
        b"/usr/share/applications/browser.desktop /usr/share/dbus-1/services/com.nokia.browser.service\n"
        b"N00_BROWSER_ENTRY_EXPORT\n"
        b"printf '\\nN00_BROWSER_ENTRIES_EXIT_%s\\n' $?; printf 'N00_BROWSER_ENTRIES_DONE\\n'\n")
    wait_line(b'N00_BROWSER_ENTRIES_DONE')
    log = (output / 'serial.log').read_bytes().replace(b'\r', b'')
    if (re.findall(rb'^N00_BROWSER_ENTRIES_EXIT_(\d+)$', log, re.M) != [b'0'] or
            log.splitlines().count(b'N00_BROWSER_ENTRIES_BEGIN') != 1):
        raise ValueError('browser entry export failed')
    entries = re.findall(rb'^([0-9a-f]{2,32766})$', log.split(b'\nN00_BROWSER_ENTRIES_BEGIN\n')[-1], re.M)
    if len(entries) != 2:
        raise ValueError('browser entry export is incomplete or ambiguous')
    replacements = {}
    info['entries'] = {}
    for index, ((name, (target, expected)), encoded) in enumerate(zip(ENTRIES.items(), entries)):
        adapted = adapt_entry(bytes.fromhex(encoded.decode()), expected)
        upload(adapted, '/tmp/n00-ui-helpers/' + name, f'N00_BROWSER_ENTRY_{index}')
        digest = hashlib.md5(adapted).hexdigest()
        replacements[b'@DESKTOP_MD5@' if index == 0 else b'@SERVICE_MD5@'] = digest.encode()
        info['entries'][target] = digest
    shell = Path(__file__).with_name('browser-setup-guest.sh').read_bytes()
    for placeholder, value in replacements.items():
        if shell.count(placeholder) != 1:
            raise ValueError('browser setup identity placeholder changed')
        shell = shell.replace(placeholder, value)
    upload(shell, '/tmp/n00-ui-helpers/browser-setup-guest.sh', 'N00_BROWSER_SETUP_SCRIPT')


def validate_setup(data, info):
    data = data.replace(b'\r', b'')
    reports = re.findall(rb'^N00_BROWSER_SETUP_BEGIN\n(.*?)^N00_BROWSER_SETUP_END$', data, re.M | re.S)
    if (len(reports) != 1 or data.splitlines().count(b'N00_BROWSER_SETUP_BEGIN') != 1 or
            data.splitlines().count(b'N00_BROWSER_SETUP_END') != 1):
        raise ValueError('browser setup report is missing or ambiguous')
    expected = {'/usr/bin/grob': '6162b4b46f28d53e93b9fcba7f4f3f7b',
        '/usr/bin/QtWebProcess': '5f4bff7d2401dd97cc9f88b1e4b02127',
        '/usr/lib/libQtWebKit2experimental.so.4': 'd93364105cdecaf69b53571275480d04',
        '/tmp/n00-ui-helpers/n00-browser.so': info['helper_md5'], **info['entries']}
    hashes = re.findall(rb'^([0-9a-f]{32})  (/[^\n]+)$', reports[0], re.M)
    if len(hashes) != len(expected) or {p.decode(): h.decode() for h, p in hashes} != expected:
        raise ValueError('browser setup identities changed')
    mounts = re.findall(rb'^tmpfs (/usr/share/[^ ]+) tmpfs [^\n]+$', reports[0], re.M)
    if sorted(p.decode() for p in mounts) != sorted(info['entries']):
        raise ValueError('browser entries must use temporary memory mounts')
