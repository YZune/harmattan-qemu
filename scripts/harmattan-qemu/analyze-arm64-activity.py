#!/usr/bin/env python3
"""Validate a bounded Cocoa activity experiment and retain every trace record."""
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import re

SCANOUT_PATH = Path(__file__).with_name('analyze-arm64-scanout.py')
SPEC = importlib.util.spec_from_file_location('scanout_profile', SCANOUT_PATH)
SCANOUT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCANOUT)
# NSProcessInfo.h: NSActivityUserInitiatedAllowingIdleSystemSleep.
# No idle-system/display-sleep inhibition or latency-critical flags.
ACTIVITY_OPTIONS = 0x00FFFFFF & ~(1 << 20)
FIELDS = {
    'lifecycle': {'start_ns', 'phase', 'enabled', 'options'},
    'observe': {'start_ns', 'active', 'window_visible', 'occlusion'},
}


def parse_line(line):
    if re.match(r'(?:\d+@\d+\.\d+: )?n00_(?:profile|scanout)_', line):
        return SCANOUT.parse_line(line)
    match = re.fullmatch(r'(?:\d+@\d+\.\d+: )?n00_activity_(\w+) (.+)\n?', line)
    if not match or match[1] not in FIELDS:
        raise ValueError('unknown activity trace record; do not discard diagnostics')
    kind, data = match.groups()
    values = {}
    for token in data.split():
        field = re.fullmatch(r'(\w+)=(\d+)', token)
        if not field or field[1] in values:
            raise ValueError('malformed or duplicate activity field')
        values[field[1]] = int(field[2])
    if values.keys() != FIELDS[kind] or not 0 < values['start_ns'] < 1 << 63:
        raise ValueError('missing/unexpected activity field or invalid clock')
    booleans = ('phase', 'enabled') if kind == 'lifecycle' else ('active', 'window_visible')
    if any(values[key] not in (0, 1) for key in booleans):
        raise ValueError('invalid activity boolean or phase')
    if kind == 'lifecycle' and values['options'] != ACTIVITY_OPTIONS * values['enabled']:
        raise ValueError('unexpected activity options, including any sleep-inhibiting flags')
    if kind == 'observe' and not 0 <= values['occlusion'] < 1 << 64:
        raise ValueError('invalid window occlusion mask')
    return {'event': 'activity_' + kind, **values}


def observations(records):
    states = Counter((r['active'], r['window_visible'], r['occlusion']) for r in records)
    return {
        'count': len(records),
        'first_ns': min((r['start_ns'] for r in records), default=None),
        'last_ns': max((r['start_ns'] for r in records), default=None),
        'states': [dict(active=bool(a), window_visible=bool(v), occlusion=o, count=count)
                   for (a, v, o), count in sorted(states.items())],
        'scope': 'AppKit state when existing update blocks execute, not continuous visibility, App Nap status, or presented FPS',
    }


def validate_lifecycle(records, environment):
    if any(environment.get(key) != '1' for key in
           ('HARMATTAN_UI_ACTIVITY_PROBE', 'HARMATTAN_UI_SCANOUT_PROBE', 'HARMATTAN_UI_PROFILE')):
        raise ValueError('requires the explicit trace-enabled activity diagnostic')
    setting = environment.get('N00_COCOA_ACTIVITY')
    if setting not in ('0', '1'):
        raise ValueError('requires an explicit activity setting')
    lifecycle = [r for r in records if r['event'] == 'activity_lifecycle']
    if len(lifecycle) != 2 or [r['phase'] for r in lifecycle] != [0, 1]:
        raise ValueError('activity begin/end not paired exactly once')
    for record in lifecycle:
        if record['enabled'] != int(setting) or record['options'] != ACTIVITY_OPTIONS * int(setting):
            raise ValueError('activity lifecycle differs from requested setting')
    if lifecycle[0]['start_ns'] >= lifecycle[1]['start_ns']:
        raise ValueError('activity end must follow begin')
    return lifecycle


def analyze(records, measurements, names, environment):
    lifecycle = validate_lifecycle(records, environment)
    begin, end = (r['start_ns'] for r in lifecycle)
    observed = [r for r in records if r['event'] == 'activity_observe']
    if not observed or any(not begin <= r['start_ns'] <= end for r in observed):
        raise ValueError('missing observations or observation outside activity lifetime')
    other = [r for r in records if r['event'] not in ('activity_lifecycle', 'activity_observe')]
    known = set(SCANOUT.BASE.FIELDS) | {'scanout_' + name for name in SCANOUT.FIELDS}
    if any(r['event'] not in known for r in other):
        raise ValueError('unknown non-activity event')
    result = SCANOUT.analyze(other, measurements, names, environment, False)
    result['activity_lifecycle'] = lifecycle
    result['activity_seconds'] = (end - begin) / 1e9
    result['whole_run']['appkit_observations'] = observations(observed)
    for response in result['responses'].values():
        if not begin <= response['posix_begin_ns'] <= response['posix_end_ns'] <= end:
            raise ValueError('interaction outside activity lifetime')
        response['appkit_observations'] = observations([r for r in observed if
            response['posix_begin_ns'] <= r['start_ns'] <= response['posix_end_ns']])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--matrix', type=Path, required=True)
    parser.add_argument('--wire-header', type=Path, required=True)
    args = parser.parse_args()
    entries = json.loads(args.matrix.read_text())
    names = SCANOUT.BASE.wire_names(args.wire_header.read_text())
    results, destinations = [], []
    for index, entry in enumerate(entries):
        if entry['command'][-1] != '--performance-diagnostic':
            raise ValueError('activity experiment must use Cocoa')
        run = Path(entry['run_directory'])
        trace = run / 'profile.log'
        if trace.stat().st_size > 256 * 1024 * 1024:
            raise ValueError('trace exceeds bounded analyzer limit')
        with trace.open() as stream:
            records = [parse_line(line) for line in stream]
        app_path = run / 'ui/application-result.json'
        measurements_path = run / 'ui/performance-measurements.json'
        app = json.loads(app_path.read_text())
        measurements = json.loads(measurements_path.read_text())
        if app.get('measurements') != measurements or app['qemu_sha256'] != entry['qemu_sha256']:
            raise ValueError('application and matrix inputs do not agree')
        result = analyze(records, measurements, names, entry['environment'])
        result.update(label=entry['label'], matrix_index=index, controller_exit=entry['controller_exit'])
        result['application_outcome'] = {key: app.get(key) for key in
            ('functional_checks_passed', 'host_graphics_clean', 'passed', 'qemu_exit', 'error', 'qemu_sha256')}
        result['sha256'] = {label: hashlib.sha256(path.read_bytes()).hexdigest() for label, path in
            (('trace', trace), ('application', app_path), ('measurements', measurements_path),
             ('matrix', args.matrix), ('wire_header', args.wire_header), ('analyzer', Path(__file__)),
             ('scanout_analyzer', SCANOUT_PATH), ('base_analyzer', SCANOUT.BASE_PATH))}
        destination = run / 'activity-analysis.json'
        if destination.exists():
            raise FileExistsError(destination)
        results.append(result)
        destinations.append(destination)
    matrix_output = args.matrix.with_name('activity-analysis.json')
    if not results or matrix_output.exists():
        raise ValueError('empty matrix or output already exists')
    # Parse and validate every run before producing any reports.
    for destination, result in zip(destinations, results):
        with destination.open('x') as output:
            output.write(json.dumps(result, indent=2) + '\n')
    with matrix_output.open('x') as output:
        output.write(json.dumps(results, indent=2) + '\n')
    print(f'Analyzed {len(results)} runs, including every original activity/scanout/profile record')


if __name__ == '__main__':
    main()
