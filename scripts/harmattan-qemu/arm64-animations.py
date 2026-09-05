"""Pinned compositor-only matrix adaptation; historical profiles stay unchanged."""
import hashlib
import os
from pathlib import Path
import re
import subprocess

LIBRARY = '/usr/lib/libmcompositor.so.1.1.3'
LIBRARY_MD5 = '49985bb59bf13ae22d20075feb11818a'
HELPER = '/tmp/n00-compositor-matrices.so'


def enabled(mode, interactive):
    if mode not in (None, 'on', 'off'):
        raise ValueError('invalid compositor animation mode')
    return interactive if mode is None else mode == 'on'


def prepare(splash=False, handoff=False):
    if not isinstance(splash, bool) or not isinstance(handoff, bool):
        raise ValueError('compositor build selectors must be bools')
    if splash and handoff:
        raise ValueError('display handoff is currently validated only with splash off')
    scripts = Path(__file__).resolve().parent
    variant = 'handoff' if handoff else ('splash' if splash else 'matrices')
    subprocess.run(['sh', str(scripts / 'build-compositor-guest.sh'), *([] if variant == 'matrices' else [f'--{variant}'])], check=True)
    work = Path(os.environ.get('HARMATTAN_PORT_WORKSPACE', scripts.parents[1] / 'extracted/qemu-arm64-port'))
    binary = (work / f'compositor-guest/n00-compositor-{variant}.so').read_bytes()
    if len(binary) < 52 or binary[:7] != b'\x7fELF\x01\x01\x01' or binary[16:20] != b'\x03\x00\x28\x00':
        raise ValueError('compositor helper is not an ARM ELF32 shared library')
    info = {'helper_sha256': hashlib.sha256(binary).hexdigest(),
            'helper_md5': hashlib.md5(binary).hexdigest(),
            'source_sha256': hashlib.sha256((scripts / 'compositor-matrices-guest.c').read_bytes()).hexdigest(),
            'restacker_source_sha256': hashlib.sha256((scripts / 'compositor-restacker-guest.c').read_bytes()).hexdigest(),
            'pixmap_source_sha256': hashlib.sha256((scripts / 'compositor-pixmap-guest.c').read_bytes()).hexdigest(),
            'controller_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'original_library_md5': LIBRARY_MD5,
            'splash_repairs': splash,
            'display_handoff': handoff,
            'scope': 'process-local compositor adaptation; original shaders, easing and application executables'}
    if splash:
        info['splash_source_sha256'] = hashlib.sha256((scripts / 'compositor-splash-guest.c').read_bytes()).hexdigest()
    if handoff:
        info['handoff_source_sha256'] = hashlib.sha256((scripts / 'compositor-handoff-guest.c').read_bytes()).hexdigest()
        info['input_handoff_source_sha256'] = hashlib.sha256((scripts / 'compositor-input-handoff-guest.c').read_bytes()).hexdigest()
    return binary, info


def validate_handoff(data, minimum=1):
    if type(minimum) is not int or minimum < 1:
        raise ValueError('handoff minimum must be positive')
    data = data.replace(b'\r', b'')
    if b'N00_COMPOSITOR_HANDOFF_ERROR' in data:
        raise ValueError('display handoff adaptation failed')
    reports = re.findall(rb'(?:^|\n)N00_ANIMATIONS_BEGIN\n(.*?)\nN00_ANIMATIONS_END\n', data, re.S)
    if not reports or any(data.splitlines().count(marker) != len(reports)
                          for marker in (b'N00_ANIMATIONS_BEGIN', b'N00_ANIMATIONS_END')):
        raise ValueError('missing or incomplete handoff reports')
    previous = []
    for report in reports:
        events = re.findall(rb'^N00_COMPOSITOR_HANDOFF_(PRESENTED|RELEASED) id=(\d+)$', report, re.M)
        if len(events) != sum(line.startswith(b'N00_COMPOSITOR_HANDOFF_') for line in report.splitlines()):
            raise ValueError('malformed display handoff event')
        if events[:len(previous)] != previous:
            raise ValueError('display handoff history changed')
        for i, (event, identity) in enumerate(events):
            if event != (b'PRESENTED' if i % 2 == 0 else b'RELEASED') or int(identity) != i // 2 + 1:
                raise ValueError('unbalanced or reordered display handoff')
        previous = events
    if len(previous) % 2 or len(previous) // 2 < minimum:
        raise ValueError('missing or unreleased display handoff')
    return {'completed': len(previous) // 2, 'retained_pixmaps_pending': 0,
            'scope': 'runtime handoff and release only; full frames, motion and GPU have independent gates'}


def validate_input_handoff(data, minimum=2):
    records = re.findall(rb'(?:^|\n)N00_ANIMATIONS_BEGIN\n(.*?)\nN00_ANIMATIONS_END\n', data.replace(b'\r',b''), re.S)
    if not records:
        raise ValueError('missing input handoff runtime report')
    lines = [line for line in records[-1].splitlines() if line.startswith(b'N00_COMPOSITOR_INPUT_HANDOFF_')]
    current, shared, completed = None, False, []
    for line in lines:
        match = re.fullmatch(rb'N00_COMPOSITOR_INPUT_HANDOFF_(PRESERVED|SHARED|RESTORED) id=([1-9]\d*) parent=([1-9a-f][0-9a-f]*) input=([1-9a-f][0-9a-f]*) reason=([a-z-]+)',line)
        if not match:
            raise ValueError('invalid input handoff marker')
        phase, ident, parent, input_window, reason = match.groups()
        identity = (int(ident),parent,input_window)
        if phase == b'PRESERVED':
            if current is not None or identity[0] != len(completed)+1 or reason != b'input-map' or parent == input_window:
                raise ValueError('overlapping or invalid input handoff')
            current = identity
            shared = False
        elif phase == b'SHARED':
            if current != identity or shared or reason != b'parent-backing':
                raise ValueError('invalid shared parent backing')
            shared = True
        else:
            if current != identity or not shared or reason not in (b'direct',b'replacement',b'parent-unmap',b'parent-destroy'):
                raise ValueError('unpaired input handoff restore')
            completed.append(dict(id=identity[0],parent=parent.decode(),input=input_window.decode(),reason=reason.decode()))
            current = None
    if current is not None or len(completed) < minimum:
        raise ValueError('input handoff left root preservation active or did not exercise it')
    return dict(completed=completed,root_background_restored=True,
                scope='balanced original input/app display handoff; visible frames have a separate continuous pixel gate')


def validate_serial(data, helper_md5, minimum_reports=3, require_root_guard=False):
    data = data.replace(b'\r', b'')
    records = re.findall(rb'(?:^|\n)N00_ANIMATIONS_BEGIN\n(.*?)\nN00_ANIMATIONS_END\n', data, re.S)
    lines = data.splitlines()
    if len(records) < minimum_reports or any(lines.count(marker) != len(records)
            for marker in (b'N00_ANIMATIONS_BEGIN', b'N00_ANIMATIONS_END')):
        raise ValueError('missing or incomplete compositor adaptation reports')
    pids = set()
    for record in records:
        def unique(pattern):
            values = re.findall(pattern, record, re.M)
            if len(values) != 1:
                raise ValueError('missing or ambiguous compositor adaptation identity')
            return values[0]
        pids.add(int(unique(rb'^N00_ANIMATIONS_PID (\d+)$')))
        for path, digest in ((LIBRARY, LIBRARY_MD5), (HELPER, helper_md5)):
            if unique(rb'^([0-9a-f]{32})  ' + re.escape(path.encode()) + rb'$').decode() != digest:
                raise ValueError('compositor library or helper was replaced')
        if unique(rb'^LD_PRELOAD=([^\n]+)$').decode() != HELPER:
            raise ValueError('unexpected compositor preload')
        if (b'N00_ANIMATIONS_MAPPED' not in record.splitlines() or
                b'N00_COMPOSITOR_WORLD_CACHE_ACTIVE' not in record.splitlines() or
                b'N00_COMPOSITOR_PROJECTION_APPLIED' not in record.splitlines() or
                b'N00_ANIMATIONS_PROCESS_SCOPE_OK' not in record.splitlines()):
            raise ValueError('adaptation did not run or leaked into another process')
        if any(marker in record for marker in (b'N00_COMPOSITOR_MATRICES_ERROR', b'N00_COMPOSITOR_RESTACKER_ERROR', b'N00_COMPOSITOR_PIXMAP_ERROR', b'N00_COMPOSITOR_INPUT_HANDOFF_ERROR')):
            raise ValueError('compositor adaptation failed')
        if require_root_guard and record.splitlines().count(b'N00_COMPOSITOR_ROOT_CONFIGURE_IGNORED') != 1:
            raise ValueError('root ConfigureNotify was not excluded from child stacking')
    if len(pids) != 1 or 0 in pids:
        raise ValueError('compositor restarted during animation observations')
    return {'pid': pids.pop(), 'reports': len(records), 'helper_mapped': True,
            'projection_initialized': True, 'world_cache_invalidated_on_bind': True,
            'root_configure_guard_observed': all(b'N00_COMPOSITOR_ROOT_CONFIGURE_IGNORED' in r.splitlines() for r in records),
            'unavailable_pixmap_observations': len(re.findall(rb'^N00_COMPOSITOR_PIXMAP_PENDING drawable=[0-9a-f]+$', records[-1], re.M)),
            'scope': 'runtime activation only; intermediate frames require the separate transition probe'}
