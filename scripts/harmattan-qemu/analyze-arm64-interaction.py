#!/usr/bin/env python3
"""Validate input-scoped activity lifetimes without filtering original traces."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re

ACTIVITY_PATH = Path(__file__).with_name('analyze-arm64-activity.py')
SPEC = importlib.util.spec_from_file_location('activity_profile', ACTIVITY_PATH)
ACTIVITY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ACTIVITY)
TIMEOUT_NS = 8_000_000_000
FIELDS = {
    'config': {'enabled', 'timeout_ms'},
    'input': {'start_ns', 'kind', 'accepted', 'held'},
    'transition': {'start_ns', 'phase', 'reason', 'generation', 'deadline_ns', 'options'},
    'renew': {'start_ns', 'generation', 'deadline_ns'},
}


def parse_line(line):
    if re.match(r'(?:\d+@\d+\.\d+: )?n00_(?:profile|scanout|activity)_', line):
        return ACTIVITY.parse_line(line)
    match = re.fullmatch(r'(?:\d+@\d+\.\d+: )?n00_lease_(\w+) (.+)\n?', line)
    if not match or match[1] not in FIELDS:
        raise ValueError('unknown lease trace record')
    kind, data = match.groups()
    values = {}
    for token in data.split():
        field = re.fullmatch(r'(\w+)=(\d+)', token)
        if not field or field[1] in values:
            raise ValueError('malformed or duplicated lease field')
        values[field[1]] = int(field[2])
    if values.keys() != FIELDS[kind]:
        raise ValueError('missing or unexpected lease fields')
    if kind == 'config':
        if values['enabled'] not in (0, 1) or values['timeout_ms'] * 1_000_000 != TIMEOUT_NS:
            raise ValueError('invalid lease configuration')
    else:
        if not 0 < values['start_ns'] < 1 << 63:
            raise ValueError('invalid lease clock')
        if kind == 'input':
            if values['kind'] not in range(5) or values['accepted'] not in (0, 1) or values['held'] not in (0, 1):
                raise ValueError('invalid input kind or boolean')
        else:
            if not 0 < values['generation'] < 1 << 64 or not 0 < values['deadline_ns'] < 1 << 63:
                raise ValueError('invalid generation or deadline')
            if kind == 'transition' and (values['phase'] not in (0, 1) or values['reason'] not in range(4) or
                    values['options'] != ACTIVITY.ACTIVITY_OPTIONS or
                    (values['phase'] == 0 and values['reason'] != 0) or
                    (values['phase'] == 1 and values['reason'] == 0)):
                raise ValueError('invalid transition or activity options')
    return {'event': 'lease_' + kind, **values}


def lifetimes(records, enabled):
    config = [r for r in records if r['event'] == 'lease_config']
    if config != [dict(event='lease_config', enabled=int(enabled), timeout_ms=8000)]:
        raise ValueError('lease configuration must match exactly once')
    current, pending, generation, previous = None, None, 0, 0
    result, inputs = [], []
    for record in records:
        kind = record['event']
        if kind == 'lease_config':
            continue
        if record['start_ns'] < previous:
            raise ValueError('lease main-queue event clock regressed')
        previous = record['start_ns']
        if kind == 'lease_input':
            if pending is not None or bool(record['held']) != (current is not None):
                raise ValueError('input does not match current lease state')
            if record['accepted'] and not enabled:
                raise ValueError('disabled configuration accepted an activity request')
            pending = record if record['accepted'] else None
            inputs.append(record)
        elif kind == 'lease_renew' or (kind == 'lease_transition' and record['phase'] == 0):
            if pending is None or record['deadline_ns'] != pending['start_ns'] + TIMEOUT_NS:
                raise ValueError('begin/renew not linked to the immediately preceding input')
            if record['start_ns'] >= record['deadline_ns']:
                raise ValueError('activity already expired when acquired or renewed')
            if kind == 'lease_renew':
                if current is None or record['generation'] != generation:
                    raise ValueError('renew without a matching lease')
                current['renewals'] += 1
            else:
                if current is not None or record['generation'] != generation + 1:
                    raise ValueError('overlapping or nonsequential lease')
                generation += 1
                current = dict(generation=generation, begin_ns=record['start_ns'],
                               first_input_ns=pending['start_ns'], renewals=0)
            current.update(last_input_ns=pending['start_ns'], deadline_ns=record['deadline_ns'])
            pending = None
        elif kind == 'lease_transition' and record['phase'] == 1:
            if (pending is not None or current is None or record['generation'] != generation or
                    record['deadline_ns'] != current['deadline_ns']):
                raise ValueError('unpaired end or incorrect final deadline')
            if record['reason'] == 1 and record['start_ns'] < current['deadline_ns']:
                raise ValueError('activity released before the idle deadline')
            current.update(end_ns=record['start_ns'], end_reason=record['reason'],
                           held_seconds=(record['start_ns'] - current['begin_ns']) / 1e9)
            if record['reason'] == 1:
                current['expiry_lateness_ms'] = (record['start_ns'] - current['deadline_ns']) / 1e6
            result.append(current)
            current = None
        else:
            raise ValueError('unknown lease event')
    if current is not None or pending is not None or not inputs:
        raise ValueError('unfinished lease/input or no observed input')
    return result, inputs


def validate_checks(intervals, checks, enabled):
    holds = checks['idle_checks']
    if [h['after_stage'] for h in holds] != ['calculator-sum', 'calculator-returned', 'calculator-reopened']:
        raise ValueError('missing ordered idle checks')
    result = []
    for hold in holds:
        begin, end = hold['posix_begin_ns'], hold['posix_end_ns']
        if end - begin < 9_900_000_000:
            raise ValueError('extra idle interval too short')
        releases = [r for r in intervals if r['end_reason'] == 1 and begin <= r['end_ns'] <= end]
        starts = [r for r in intervals if begin <= r['begin_ns'] <= end]
        if enabled and (len(releases) != 1 or starts):
            raise ValueError('extra idle did not release exactly once without new activity')
        result.append(dict(after_stage=hold['after_stage'], expiry_generations=[r['generation'] for r in releases]))
    exit_check = checks['exit_rearm']
    if exit_check['posix_begin_ns'] >= exit_check['posix_end_ns']:
        raise ValueError('invalid exit rearm interval')
    if enabled:
        final = intervals[-1]
        if (not exit_check['posix_begin_ns'] <= final['begin_ns'] <= exit_check['posix_end_ns'] or
                final['end_reason'] != 3 or not exit_check['posix_end_ns'] <= final['end_ns'] < final['deadline_ns']):
            raise ValueError('exit did not release the explicitly rearmed lease')
    return result


def analyze(records, measurements, names, environment):
    if environment.get('HARMATTAN_UI_INTERACTION_PROBE') != '1' or environment.get('N00_COCOA_ACTIVITY') != '0':
        raise ValueError('requires input probe without whole-run activity')
    setting = environment.get('N00_COCOA_INTERACTION')
    if setting not in ('0', '1'):
        raise ValueError('explicit interaction setting required')
    enabled = setting == '1'
    lease_records = [r for r in records if r['event'].startswith('lease_')]
    intervals, inputs = lifetimes(lease_records, enabled)
    result = ACTIVITY.analyze([r for r in records if not r['event'].startswith('lease_')],
                              measurements, names, environment)
    begin, end = (r['start_ns'] for r in result['activity_lifecycle'])
    if any(not begin <= r['start_ns'] <= end for r in lease_records if 'start_ns' in r):
        raise ValueError('lease event outside process lifetime')
    result['input_activity'] = dict(enabled=enabled, timeout_ms=8000, lifetimes=intervals,
        observed_inputs=len(inputs), accepted_inputs=sum(r['accepted'] for r in inputs),
        idle_checks=validate_checks(intervals, measurements['interaction_checks'], enabled),
        scope='input-driven Foundation activity lifetimes, not direct App Nap/QoS/core-residency measurements')
    for response in result['responses'].values():
        at_end = [r['generation'] for r in intervals if r['begin_ns'] <= response['posix_end_ns'] <= r['end_ns']]
        if enabled and len(at_end) != 1:
            raise ValueError('target framebuffer observed without one active lease')
        response['lease_generation_at_target_frame'] = at_end
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--matrix', type=Path, required=True)
    parser.add_argument('--wire-header', type=Path, required=True)
    args = parser.parse_args()
    entries = json.loads(args.matrix.read_text())
    names = ACTIVITY.SCANOUT.BASE.wire_names(args.wire_header.read_text())
    results, destinations = [], []
    for index, entry in enumerate(entries):
        if entry['command'][-1] != '--performance-diagnostic':
            raise ValueError('input activity requires Cocoa')
        run = Path(entry['run_directory'])
        trace = run / 'profile.log'
        if trace.stat().st_size > 256 * 1024 * 1024:
            raise ValueError('trace exceeds bounded analyzer limit')
        with trace.open() as stream:
            records = [parse_line(line) for line in stream]
        app_path = run / 'ui/application-result.json'
        measure_path = run / 'ui/performance-measurements.json'
        checks_path = run / 'ui/interaction-checks.json'
        app, measures, checks = (json.loads(p.read_text()) for p in (app_path, measure_path, checks_path))
        if (app.get('measurements') != measures or measures['interaction_checks'] != checks or
                app['qemu_sha256'] != entry['qemu_sha256']):
            raise ValueError('application, measurements, checks and matrix do not agree')
        result = analyze(records, measures, names, entry['environment'])
        result.update(label=entry['label'], matrix_index=index, controller_exit=entry['controller_exit'])
        result['application_outcome'] = {key: app.get(key) for key in
            ('functional_checks_passed', 'host_graphics_clean', 'passed', 'qemu_exit', 'error', 'qemu_sha256')}
        result['sha256'] = {label: hashlib.sha256(path.read_bytes()).hexdigest() for label, path in
            (('trace', trace), ('application', app_path), ('measurements', measure_path), ('checks', checks_path),
             ('matrix', args.matrix), ('wire_header', args.wire_header), ('analyzer', Path(__file__)),
             ('activity_analyzer', ACTIVITY_PATH), ('scanout_analyzer', ACTIVITY.SCANOUT_PATH),
             ('base_analyzer', ACTIVITY.SCANOUT.BASE_PATH))}
        destination = run / 'interaction-analysis.json'
        if destination.exists():
            raise FileExistsError(destination)
        results.append(result)
        destinations.append(destination)
    output = args.matrix.with_name('interaction-analysis.json')
    if not results or output.exists() or len(set(destinations)) != len(destinations):
        raise ValueError('empty/duplicate matrix or existing output')
    for destination, result in zip(destinations, results):
        with destination.open('x') as stream:
            stream.write(json.dumps(result, indent=2) + '\n')
    with output.open('x') as stream:
        stream.write(json.dumps(results, indent=2) + '\n')
    print(f'Validated {len(results)} complete input-activity experiments; all original trace events retained')


if __name__ == '__main__':
    main()
