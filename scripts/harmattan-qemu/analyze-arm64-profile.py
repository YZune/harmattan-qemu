#!/usr/bin/env python3
"""Summarize optional N00 wall-time probes; never infer displayed FPS."""
import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import re

FIELDS = {
    'gles': {'client', 'api', 'call', 'start_ns', 'dispatch_ns', 'worker_ns'},
    'dss': {'start_ns', 'total_ns', 'copy_ns', 'first', 'last', 'cols', 'rows'},
    'cocoa_refresh': {'start_ns', 'total_ns', 'gfx_ns'},
    'cocoa_queue': {'start_ns', 'wait_ns', 'w', 'h'},
    'cocoa_draw': {'start_ns', 'total_ns'},
}


def parse_line(line):
    match = re.fullmatch(r'(?:\d+@\d+\.\d+: )?n00_profile_(\w+) (.+)\n?', line)
    if not match or match[1] not in FIELDS:
        raise ValueError('unexpected trace line; do not discard possible diagnostics')
    kind, values = match.groups()
    fields = {}
    for token in values.split():
        item = re.fullmatch(r'(\w+)=(-?\d+)', token)
        if not item or item[1] in fields:
            raise ValueError('malformed or duplicate trace field')
        fields[item[1]] = int(item[2])
    if fields.keys() != FIELDS[kind] or fields['start_ns'] <= 0:
        raise ValueError('missing/unexpected fields or invalid clock')
    if any(value < 0 for name, value in fields.items() if name != 'first'):
        raise ValueError('negative duration or invalid field')
    if kind == 'gles' and (fields['api'] > 2 or fields['worker_ns'] > fields['dispatch_ns']):
        raise ValueError('invalid GLES timing nesting')
    if kind == 'dss' and (fields['copy_ns'] > fields['total_ns'] or
                          fields['first'] < -1 or fields['first'] >= fields['rows'] or
                          fields['last'] >= fields['rows'] or fields['cols'] <= 0 or fields['rows'] <= 0):
        raise ValueError('invalid DSS timing or changed-row bounds')
    if kind == 'cocoa_refresh' and fields['gfx_ns'] > fields['total_ns']:
        raise ValueError('invalid Cocoa timing nesting')
    return {'event': kind, **fields}


def duration(record):
    return record.get('dispatch_ns', record.get('total_ns', record.get('wait_ns')))


def align_clock(python_seconds, calibration):
    start, end = calibration['start'], calibration['end']
    for sample in (start, end):
        if sample['posix_ns'] - sample['python_ns'] != sample['posix_minus_python_ns'] or sample['bracket_ns'] < 0:
            raise ValueError('invalid clock calibration')
    width = end['python_ns'] - start['python_ns']
    instant = round(python_seconds * 1e9)
    if width <= 0 or not start['python_ns'] <= instant <= end['python_ns']:
        raise ValueError('timed window outside clock calibration')
    weight = (instant - start['python_ns']) / width
    offset = start['posix_minus_python_ns'] * (1 - weight) + end['posix_minus_python_ns'] * weight
    return round(instant + offset)


def quantiles(values):
    values = sorted(values)
    if not values:
        return dict(count=0, sum_ms=0, p50_ms=None, p95_ms=None, max_ms=None)
    def percentile(fraction):
        return values[max(0, math.ceil(len(values) * fraction) - 1)] / 1e6
    return dict(count=len(values), sum_ms=sum(values) / 1e6,
                p50_ms=percentile(.5), p95_ms=percentile(.95), max_ms=values[-1] / 1e6)


def wire_names(text):
    result = {}
    for api, prefix in enumerate(('egl', 'es11', 'es20')):
        match = re.search(r'enum n00_' + prefix + r'_call\s*\{([^}]+)\}', text)
        if not match:
            raise ValueError('missing fixed wire enum')
        names = re.findall(r'N00_' + prefix + r'_(\w+)\s*,?', match[1])
        if not names or names[-1] != 'count' or '=' in match[1]:
            raise ValueError('unexpected non-sequential wire enum')
        result.update({(api, call): name for call, name in enumerate(names[:-1])})
    return result


def summarize(records, names):
    by_event, by_call = defaultdict(list), defaultdict(list)
    for record in records:
        by_event[record['event']].append(record)
        if record['event'] == 'gles':
            key = (record['api'], record['call'])
            if key not in names:
                raise ValueError('trace call outside the supplied wire ABI')
            by_call[key].append(record)
    result = {'events': {}, 'top_calls': []}
    for kind in FIELDS:
        group = by_event[kind]
        entry = {'count': len(group)}
        for name in sorted(FIELDS[kind]):
            if name.endswith('_ns') and name != 'start_ns':
                entry[name] = quantiles([record[name] for record in group])
        if kind == 'gles':
            entry['transport_remainder_ns'] = quantiles([record['dispatch_ns'] - record['worker_ns'] for record in group])
        if kind == 'dss':
            entry['updates_with_dirty_rows'] = sum(record['first'] >= 0 for record in group)
        result['events'][kind] = entry
    for (api, call), group in by_call.items():
        result['top_calls'].append({'api': api, 'call': call, 'name': names[(api, call)],
                                   'dispatch': quantiles([record['dispatch_ns'] for record in group]),
                                   'worker': quantiles([record['worker_ns'] for record in group])})
    result['top_calls'].sort(key=lambda call: call['dispatch']['sum_ms'], reverse=True)
    result['top_calls'] = result['top_calls'][:15]
    return result


def analyze(records, measurements, names):
    if not measurements.get('trace_profile_enabled') or not measurements.get('post_idle_sync'):
        raise ValueError('requires a completed trace-enabled measurement')
    if not records:
        raise ValueError('empty trace is not evidence of zero cost')
    clocks = measurements['clock_alignment']
    result = {
        'scope': 'instrumented wall durations, not CPU-only/GPU time or physical presentation FPS',
        'nesting': 'worker is inside dispatch; DSS is inside Cocoa refresh; these totals must not be added',
        'window_rule': 'only events fully inside each calibrated input-to-reference interval; boundary-spanning events excluded',
        'clock_alignment': clocks,
        'clock_offset_drift_ns': clocks['end']['posix_minus_python_ns'] - clocks['start']['posix_minus_python_ns'],
        'whole_run': summarize(records, names), 'responses': {},
    }
    for label, response in measurements['responses'].items():
        end = response['samples'][-1]['end']
        begin = end - response['first_observed_match_seconds']
        first = align_clock(begin, clocks)
        last = align_clock(end, clocks)
        selected = [record for record in records if first <= record['start_ns'] and record['start_ns'] + duration(record) <= last]
        result['responses'][label] = {'wall_seconds': response['first_observed_match_seconds'],
                                       'posix_begin_ns': first, 'posix_end_ns': last,
                                       **summarize(selected, names)}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trace', type=Path, required=True)
    parser.add_argument('--measurements', type=Path, required=True)
    parser.add_argument('--wire-header', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.trace.stat().st_size > 256 * 1024 * 1024:
        parser.error('trace exceeds this bounded analyzer limit')
    with args.trace.open() as stream:
        records = [parse_line(line) for line in stream]
    measurements = json.loads(args.measurements.read_text())
    application_path = args.measurements.with_name('application-result.json')
    application = json.loads(application_path.read_text())
    if application.get('measurements') != measurements:
        parser.error('application result does not contain these exact measurements')
    result = analyze(records, measurements, wire_names(args.wire_header.read_text()))
    # Failed UI runs can be profiled diagnostically, but cannot silently
    # become accepted application/performance samples in this report.
    result['application_outcome'] = {key: application.get(key) for key in
                                     ('functional_checks_passed', 'host_graphics_clean', 'passed', 'qemu_exit', 'error', 'qemu_sha256')}
    result['sha256'] = {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in
                       (('trace', args.trace), ('measurements', args.measurements), ('application', application_path),
                        ('wire_header', args.wire_header), ('analyzer', Path(__file__)))}
    with args.output.open('x') as output:
        output.write(json.dumps(result, indent=2) + '\n')
    print(f'Analyzed {len(records)} events; {args.output}')


if __name__ == '__main__':
    main()
