#!/usr/bin/env python3
"""Analyze all scanout trace records without editing or filtering the original evidence."""
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import re

BASE_PATH = Path(__file__).with_name('analyze-arm64-profile.py')
SPEC = importlib.util.spec_from_file_location('base_profile', BASE_PATH)
BASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BASE)
FIELDS = {'frame': {'start_ns', 'enabled', 'pending'},
          'dss_config': {'timer_only'}, 'cocoa_config': {'interval_ms'}}


def parse_line(line):
    if re.match(r'(?:\d+@\d+\.\d+: )?n00_profile_', line):
        return BASE.parse_line(line)
    match = re.fullmatch(r'(?:\d+@\d+\.\d+: )?n00_scanout_(\w+) (.+)\n?', line)
    if not match or match[1] not in FIELDS:
        raise ValueError('unknown scanout trace record')
    kind, data = match.groups()
    values = {}
    for token in data.split():
        field = re.fullmatch(r'(\w+)=(\d+)', token)
        if not field or field[1] in values:
            raise ValueError('malformed or duplicated scanout field')
        values[field[1]] = int(field[2])
    if values.keys() != FIELDS[kind]:
        raise ValueError('missing or unexpected scanout fields')
    if kind == 'frame' and (values['start_ns'] <= 0 or values['pending'] & ~values['enabled']):
        raise ValueError('invalid enabled/pending mask or clock')
    if kind == 'dss_config' and values['timer_only'] not in (0, 1):
        raise ValueError('invalid timer-only setting')
    if kind == 'cocoa_config' and values['interval_ms'] not in (0, 8, 16, 33, 100):
        raise ValueError('invalid refresh interval')
    return {'event': 'scanout_' + kind, **values}


def frame_requests(records):
    return {'requests': len(records),
            'requests_with_enabled_pending_bits': sum(record['pending'] != 0 for record in records),
            'enabled_masks': dict(Counter(str(record['enabled']) for record in records)),
            'scope': 'device frame-completion requests and pending masks, not delivered CPU interrupts or FPS'}


def analyze(records, measurements, names, environment, headless):
    dss = [r for r in records if r['event'] == 'scanout_dss_config']
    cocoa = [r for r in records if r['event'] == 'scanout_cocoa_config']
    if dss != [{'event': 'scanout_dss_config', 'timer_only': int(environment['N00_SCANOUT_TIMER_ONLY'])}]:
        raise ValueError('DSS did not record the requested configuration exactly once')
    expected_cocoa = [] if headless else [{'event': 'scanout_cocoa_config', 'interval_ms': int(environment['N00_SCANOUT_REFRESH_MS'])}]
    if cocoa != expected_cocoa:
        raise ValueError('Cocoa did not record the requested configuration exactly once')
    result = BASE.analyze([r for r in records if r['event'] in BASE.FIELDS], measurements, names)
    frames = [r for r in records if r['event'] == 'scanout_frame']
    result['scanout_configuration'] = dss + cocoa
    result['whole_run']['frame_requests'] = frame_requests(frames)
    for response in result['responses'].values():
        response['frame_requests'] = frame_requests([r for r in frames if
            response['posix_begin_ns'] <= r['start_ns'] <= response['posix_end_ns']])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--matrix', type=Path, required=True)
    parser.add_argument('--wire-header', type=Path, required=True)
    args = parser.parse_args()
    results = []
    names = BASE.wire_names(args.wire_header.read_text())
    for entry in json.loads(args.matrix.read_text()):
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
        result = analyze(records, measurements, names, entry['environment'], entry['command'][-1] == '--performance-headless-diagnostic')
        result['label'] = entry['label']
        result['application_outcome'] = {key: app.get(key) for key in
            ('functional_checks_passed', 'host_graphics_clean', 'passed', 'qemu_exit', 'error', 'qemu_sha256')}
        result['sha256'] = {label: hashlib.sha256(path.read_bytes()).hexdigest() for label, path in
            (('trace', trace), ('application', app_path), ('measurements', measurements_path), ('matrix', args.matrix),
             ('wire_header', args.wire_header), ('analyzer', Path(__file__)), ('base_analyzer', BASE_PATH))}
        with (run / 'scanout-analysis.json').open('x') as output:
            output.write(json.dumps(result, indent=2) + '\n')
        results.append(result)
    with args.matrix.with_name('analysis.json').open('x') as output:
        output.write(json.dumps(results, indent=2) + '\n')
    print(f'Analyzed {len(results)} runs with all original trace records retained')


if __name__ == '__main__':
    main()
