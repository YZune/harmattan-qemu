"""Snapshot-only original splash protocol; publication and rendering are separate."""
import hashlib
from pathlib import Path
import re

HELPER_ROOT = '/tmp/n00-ui-helpers'
BASE_INVOKER_MD5 = 'ca6f09e9035fdc66a34daae5d48e9083'
FILES = ('N00X11.pm', 'splash-screen-guest.pl', 'invoker-direct-qemu.sh')
CALC_PORTRAIT = '/usr/share/themes/blanco/meegotouch/images/splash/meegotouch-calculator-splash.jpg'


def enabled(mode, interactive):
    if mode not in (None, 'on', 'off'):
        raise ValueError('invalid splash mode')
    # Keep opt-in until splash visuals and the remaining transition flashes
    # are separately accepted, even after the app-return repair passes.
    return mode == 'on'


def prepare():
    scripts = Path(__file__).resolve().parent
    payloads = {name: (scripts / name).read_bytes() for name in FILES}
    return payloads, {
        'base_invoker_md5': BASE_INVOKER_MD5,
        'files': {name: {'md5': hashlib.md5(data).hexdigest(), 'sha256': hashlib.sha256(data).hexdigest()}
                  for name, data in payloads.items()},
        'controller_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'scope': 'original compositor protocol and original image files; not visual or performance acceptance'}


def validate_serial(data, info, application_pid=None, minimum_reports=2):
    data = data.replace(b'\r', b'')
    reports = re.findall(rb'(?:^|\n)N00_SPLASH_REPORT_BEGIN\n(.*?)\nN00_SPLASH_REPORT_END\n', data, re.S)
    if len(reports) < minimum_reports or any(data.splitlines().count(marker) != len(reports)
            for marker in (b'N00_SPLASH_REPORT_BEGIN', b'N00_SPLASH_REPORT_END')):
        raise ValueError('missing or incomplete splash reports')
    published = []
    for report in reports:
        for name in FILES:
            target = '/usr/bin/invoker' if name == 'invoker-direct-qemu.sh' else f'{HELPER_ROOT}/{name}'
            found = re.findall(rb'^([0-9a-f]{32})  ' + re.escape(target.encode()) + rb'$', report, re.M)
            if found != [info['files'][name]['md5'].encode()]:
                raise ValueError('snapshot splash helper identity mismatch')
        log = re.findall(rb'N00_SPLASH_LOG_BEGIN\n(.*?)N00_SPLASH_LOG_END', report, re.S)
        if len(log) != 1:
            raise ValueError('missing splash publication log')
        lines = log[0].splitlines()
        entries = []
        for line in lines:
            match = re.fullmatch(rb'N00_SPLASH_PUBLISHED pid=([1-9][0-9]*) wm=([0-9a-f]{8}) portrait=([0-9a-f]+) landscape=([0-9a-f]*)', line)
            if not match or int(match[2], 16) == 0:
                raise ValueError('splash publication failed or unexpected log')
            entries.append((int(match[1]), match[2].decode(), bytes.fromhex(match[3].decode()).decode(),
                            bytes.fromhex(match[4].decode()).decode()))
        if entries[:len(published)] != published:
            raise ValueError('splash history disappeared or changed')
        published = entries
    if application_pid is not None:
        matches = [entry for entry in published if entry[0] == application_pid]
        if len(matches) != 1 or matches[0][2:] != (CALC_PORTRAIT, ''):
            raise ValueError('expected one cold-start splash for the original Calculator PID')
        if len(published) != 1:
            raise ValueError('unexpected additional splash or warm-resume publication')
    return {'reports': len(reports), 'publications': [dict(pid=p, wm=w, portrait=a, landscape=b) for p, w, a, b in published],
            'scope': 'server accepted the original protocol; visual frames require separate verification'}


def validate_repairs(data):
    # Tail snapshots repeat markers; their frequency is not an event count.
    data = data.replace(b'\r', b'')
    reports = re.findall(rb'(?:^|\n)N00_ANIMATIONS_BEGIN\n(.*?)\nN00_ANIMATIONS_END\n', data, re.S)
    if b'N00_COMPOSITOR_SPLASH_ERROR' in data or b'std::bad_alloc' in data:
        raise ValueError('splash compositor adaptation failed')
    if not any(all(marker in report.splitlines() for marker in (
            b'N00_COMPOSITOR_SPLASH_NULL_BIND_DEFERRED', b'N00_COMPOSITOR_SPLASH_CURRENT_APP_REFRESH')) for report in reports):
        raise ValueError('splash compositor repairs did not both execute')
    return {'null_bind_deferred': True, 'current_app_refreshed': True,
            'scope': 'runtime activation only; original app, input, frames and GPU require their independent gates'}
