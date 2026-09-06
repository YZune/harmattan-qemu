"""Prepare a profile-only, pinned FBReader Qt viewport adaptation."""
import hashlib
import importlib.util
import os
from pathlib import Path
import re
import subprocess

SPEC = importlib.util.spec_from_file_location('viewport_systemui', Path(__file__).with_name('arm64-systemui.py'))
systemui = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(systemui)


def prepare():
    scripts = Path(__file__).resolve().parent
    subprocess.run(['sh', str(scripts / 'build-app-viewport-guest.sh')], check=True)
    work = Path(os.environ.get('HARMATTAN_PREBUILT_HELPERS') or
                os.environ.get('HARMATTAN_PORT_WORKSPACE', scripts.parents[1] / 'extracted/qemu-arm64-port'))
    data = (work / 'app-viewport-guest/n00-app-viewport.so').read_bytes()
    if (len(data) < 52 or data[:7] != b'\x7fELF\x01\x01\x01'
            or data[16:20] != b'\x03\x00\x28\x00'):
        raise ValueError('application viewport helper is not ARM ELF32 shared code')
    md5 = hashlib.md5(data).hexdigest()
    shell = (scripts / 'app-viewport-guest.sh').read_bytes()
    if shell.count(b'@HELPER_MD5@') != 1:
        raise ValueError('application viewport helper identity placeholder changed')
    return {'n00-app-viewport.so': data,
            'app-viewport-guest.sh': shell.replace(b'@HELPER_MD5@', md5.encode())}, {
        'helper_md5': md5, 'helper_sha256': hashlib.sha256(data).hexdigest(),
        'source_sha256': hashlib.sha256((scripts / 'app-viewport-guest.c').read_bytes()).hexdigest(),
        'scope': 'FBReader 0.99.5 only, activated after guest executable and Qt library checks'}


def validate_host(data, reader_runs):
    """Compose exact reader lifecycles with the unchanged three-client gate.

    Use after independently checking the original executable and helper marker
    for each launch. QGLWidget construction still opens slot 4 before Qt deletes
    the unused widget. Each reader exit must release that slot before reuse.
    """
    if type(reader_runs) is not int or not 1 <= reader_runs <= 8:
        raise ValueError('requires 1-8 independently verified reader launches')
    lines = data.strip().split(b'\n')
    core, cycles, index = [], 0, 0
    while index < len(lines):
        if lines[index] == b'N00_GLES connect client=4 abi=2':
            # Reader cycles may only occur while all original UI clients live.
            systemui.validate_host(b'\n'.join(core) + b'\n', live=True)
            cycle = lines[index:index + 5]
            if (len(cycle) != 5
                    or not re.fullmatch(rb'N00_GLES current client=4 es=2 renderer=Apple [^\n]+', cycle[1])
                    or cycle[2:] != [
                        b'N00_GLES terminate client=4 released=1 backend=retained',
                        b'N00_GLES terminate client=4 rejected=bad-display',
                        b'N00_GLES disconnect client=4',
                    ]):
                raise ValueError('reader GPU lifecycle is incomplete or contains unexpected calls')
            cycles += 1
            index += 5
        else:
            core.append(lines[index])
            index += 1
    if cycles != reader_runs:
        raise ValueError('reader GPU cycles do not match the verified application launches')
    result = systemui.validate_host(b'\n'.join(core) + b'\n')
    result['base_ui_gpu_contexts'] = result.pop('gpu_contexts')
    result.update(peak_gpu_contexts=4, reader_lifecycles=cycles, reader_context_slot=4,
                  reader_slot_released_before_reuse=True,
                  reader_guest_api_defect='original Qt EGL double termination; NULL display correctly rejected')
    return result
