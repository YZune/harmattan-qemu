"""Add bounded idle/reacquisition checks around the unchanged framebuffer probe."""
import hashlib
import importlib.util
import json
from pathlib import Path
import time

BASE_PATH = Path(__file__).with_name('measure-arm64-ui.py')
SPEC = importlib.util.spec_from_file_location('base_ui_performance', BASE_PATH)
BASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BASE)
FrameProbe = BASE.FrameProbe
HOME_RGB = BASE.HOME_RGB
IDLE_STAGES = ('calculator-sum', 'calculator-returned', 'calculator-reopened')


def run_probe(qmp, serial, wait_line, capture, display, rotation, out, process, drain, calculator):
    checks = {'scope': 'extra idle intervals outside response/stability measurements; no presented FPS',
              'base_probe_sha256': hashlib.sha256(BASE_PATH.read_bytes()).hexdigest(),
              'idle_checks': []}
    checks_path = out / 'interaction-checks.json'

    def save():
        checks_path.write_text(json.dumps(checks, indent=2) + '\n')

    def capture_and_idle(stage):
        capture(stage)
        if stage not in IDLE_STAGES:
            return
        if qmp.call('query-status')['status'] != 'running':
            raise ValueError('QEMU must be running during the extra idle check')
        first = time.clock_gettime_ns(time.CLOCK_MONOTONIC)
        samples = [BASE.sample_process(process.pid)]
        for _ in range(2):
            drain(5)
            samples.append(BASE.sample_process(process.pid))
        last = time.clock_gettime_ns(time.CLOCK_MONOTONIC)
        if qmp.call('query-status')['status'] != 'running':
            raise ValueError('QEMU stopped during the extra idle check')
        checks['idle_checks'].append(dict(after_stage=stage, posix_begin_ns=first,
                                         posix_end_ns=last, process=BASE.summarize_cpu(samples)))
        save()
        print(f'INTERACTION: completed 10-second idle after {stage}', flush=True)

    result = BASE.run_probe(qmp, serial, wait_line, capture_and_idle, display,
                            rotation, out, process, drain, calculator)
    # After the unchanged workflow and final idle, rearm with pointer movement
    # only (no button/key). It is not a measured application response. The
    # controller will immediately quit, allowing trace validation of cleanup
    # while an assertion is held rather than after its idle expiry.
    first = time.clock_gettime_ns(time.CLOCK_MONOTONIC)
    qmp.call('input-send-event', {'events': [
        {'type': 'abs', 'data': {'axis': 'x', 'value': 0}},
        {'type': 'abs', 'data': {'axis': 'y', 'value': 0}},
    ]})
    drain(.25)
    checks['exit_rearm'] = dict(posix_begin_ns=first,
        posix_end_ns=time.clock_gettime_ns(time.CLOCK_MONOTONIC),
        scope='post-measurement pointer-only input to test normal exit with an active lease')
    result['interaction_checks'] = checks
    save()
    (out / 'performance-measurements.json').write_text(json.dumps(result, indent=2) + '\n')
    return result
