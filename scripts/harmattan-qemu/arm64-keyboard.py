"""Original Maliit/Notes input and raster repaint checks in disposable guests."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import time

SCRIPTS = Path(__file__).resolve().parent
MOTION_SPEC = importlib.util.spec_from_file_location('keyboard_motion', SCRIPTS/'probe-arm64-keyboard-transitions.py')
motion = importlib.util.module_from_spec(MOTION_SPEC)
MOTION_SPEC.loader.exec_module(motion)
LIBRARIES = {
    '/usr/bin/meego-im-uiserver': 'bf6a04592241f1764a669324a330b0f1',
    '/usr/lib/meego-im-plugins/libmeego-keyboard.so': '3436d74757597eb83207ab86158788c4',
    '/usr/lib/qt4/plugins/inputmethods/libminputcontext.so': '6877d40e5cdba786a62acaaa4ceb20c3',
}
NOTES_MD5 = '59a2e909cacfdcedf2423a85913724bd'
STAGES = ('empty', 'editor', 'typed', 'deleted', 'symbols', 'saved', 'again', 'returned')
# Original, visually reviewed PR1.3 keyboard pixels in the upright 480x314
# keyboard region. Date, caret and live word predictions lie outside it.
LAYOUT_RGB = {
    'editor':'9fd47e91c96fec2a4a71705e48ac220c22f97d77395163d31b808125bad2ee5c',
    'deleted':'cfa16d0fc81345fbaeedff039a85c11fa744cf5f33a497fa624c484cf1576b63',
    'symbols':'a76fd6f031e6b606f91a987439de7bd61ee27b48f4730549892177adb0248a87',
    'again':'9fd47e91c96fec2a4a71705e48ac220c22f97d77395163d31b808125bad2ee5c',
}


def prepare(exercise=False):
    payloads = {'input-method-guest.sh': (SCRIPTS / 'input-method-guest.sh').read_bytes()}
    if exercise:
        subprocess.run(['sh', str(SCRIPTS / 'build-keyboard-probe.sh')], check=True)
        work = Path(os.environ.get('HARMATTAN_PREBUILT_HELPERS') or os.environ.get('HARMATTAN_PORT_WORKSPACE', SCRIPTS.parents[1] / 'extracted/qemu-arm64-port'))
        payloads['keyboard-notes-read'] = (work / 'keyboard-probe/keyboard-notes-read').read_bytes()
    return payloads, {'libraries_md5': LIBRARIES,
                      'payload_sha256': {name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()}}


def unique(pattern, data, flags=re.M):
    matches = re.findall(pattern, data, flags)
    if len(matches) != 1:
        raise ValueError('missing or ambiguous keyboard evidence')
    return matches[0]


def validate_serial(data, minimum_reports=4):
    data = data.replace(b'\r', b'')
    blocks = re.findall(rb'^N00_IME_BEGIN\n(.*?)\nN00_IME_END$', data, re.M | re.S)
    if len(blocks) < minimum_reports or data.splitlines().count(b'N00_IME_BEGIN') != len(blocks) or data.splitlines().count(b'N00_IME_END') != len(blocks):
        raise ValueError('incomplete keyboard service reports')
    previous = None
    for block in blocks:
        pid = unique(rb'^N00_IME_PID ([1-9]\d*)$', block)
        process = unique(rb'^Name:\s*meego-im-uiserv\w*\nState:\s*([RS])[^\n]*\nTgid:\s*(\d+)\nPid:\s*(\d+)\nPPid:[^\n]*\nTracerPid:\s*0\nUid:\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\n', block)
        if process[1:3] != (pid, pid) or process[3:] != (b'29999',) * 4:
            raise ValueError('input method identity or UID changed')
        for path, digest in {**LIBRARIES, '/proc/' + pid.decode() + '/exe': LIBRARIES['/usr/bin/meego-im-uiserver']}.items():
            if unique(rb'^([a-f0-9]{32})  ' + re.escape(path.encode()) + rb'$', block).decode() != digest:
                raise ValueError('input method binary was replaced')
        args = unique(rb'^N00_IME_ARGUMENTS (.+)$', block).split()
        if args != [b'meego-im-uiserver', b'-use-self-composition', b'-software', b'-local-theme', b'-graphicssystem', b'raster']:
            raise ValueError('wrong input method composition path')
        if block.splitlines().count(b'N00_IME_KEYBOARD_MAPPED') != 1:
            raise ValueError('original keyboard plugin was not loaded')
        owner = unique(rb'N00_IME_OWNER_BEGIN\n(.*?)\nN00_IME_OWNER_END', block, re.M | re.S)
        if unique(rb'^\s*uint32 (\d+)$', owner) != pid:
            raise ValueError('Maliit address service has another owner')
        address = unique(rb'N00_IME_ADDRESS_BEGIN\n(.*?)\nN00_IME_ADDRESS_END', block, re.M | re.S)
        value = unique(rb'^\s*variant\s+string "(unix:abstract=/tmp/maliit-server/dbus-[a-zA-Z0-9]+,guid=[a-f0-9]{32})"$', address)
        identity = (pid, value)
        if previous is not None and previous != identity:
            raise ValueError('input method restarted during the test')
        previous = identity
    return {'pid': int(previous[0]), 'uid': 29999, 'same_instance': True, 'reports': len(blocks),
            'address': previous[1].decode(), 'composition': 'original self-composition, raster, no manual redirection'}


def portrait_crop(ppm, box):
    header = b'P6\n864 480\n255\n'
    if not ppm.startswith(header) or len(ppm) != len(header) + 864 * 480 * 3:
        raise ValueError('keyboard crop requires complete native RGB frame')
    pixels = ppm[len(header):]
    left, top, right, bottom = box
    if not (0 <= left < right <= 480 and 0 <= top < bottom <= 864):
        raise ValueError('invalid portrait region')
    return b''.join(pixels[((479-x)*864+y)*3:((479-x)*864+y)*3+3]
                    for y in range(top, bottom) for x in range(left, right))


def validate_notes(data, home, frames):
    data = data.replace(b'\r', b'')
    blocks = re.findall(rb'^N00_KEYBOARD_BEGIN_(\w+)\n(.*?)\nN00_KEYBOARD_DONE_\1$', data, re.M | re.S)
    if tuple(stage.decode() for stage, _ in blocks) != STAGES:
        raise ValueError('missing or reordered Notes observations')
    notes_pid = None
    for stage, block in blocks:
        if unique(rb'^N00_KEYBOARD_EXIT_' + stage + rb'_(\d+)$', block) != b'0':
            raise ValueError('Notes inspector failed')
        pid = unique(rb'^N00_NOTES_PID ([1-9]\d*)$', block)
        # A disk-wait sample is legitimate while Notes loads its real calendar
        # store. Progress is proved by the later text/save/foreground checks;
        # stopped, traced, zombie or replaced processes are still rejected.
        process = unique(rb'^Name:\s*notes\nState:\s*([RSD])[^\n]*\nTgid:\s*(\d+)\nPid:\s*(\d+)\nPPid:[^\n]*\nTracerPid:\s*0\nUid:\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\n', block)
        if process[1:3] != (pid,pid) or process[3:] != (b'29999',)*4:
            raise ValueError('Notes process identity mismatch')
        for path in (b'/usr/bin/notes', b'/proc/'+pid+b'/exe'):
            if unique(rb'^([a-f0-9]{32})  '+re.escape(path)+rb'$', block).decode() != NOTES_MD5:
                raise ValueError('Notes executable was replaced')
        if notes_pid is not None and pid != notes_pid:
            raise ValueError('Notes did not retain the same instance')
        notes_pid = pid
        if b'QT_IM_MODULE=MInputContext\n' not in block or b'N00_NOTES_INPUT_CONTEXT_MAPPED\n' not in block:
            raise ValueError('Notes input context missing')
        expected = [b'51656D75'] if stage in (b'saved', b'again', b'returned') else []
        rows = re.findall(rb'^N00_NOTES_TEXT_HEX ([A-F0-9]*)$', block, re.M)
        if rows != expected or int(unique(rb'^N00_NOTES_COUNT (\d+)$', block)) != len(expected):
            raise ValueError('real Notes database does not contain the expected keyboard text')
        active = unique(rb'^N00_X11_ACTIVE id=([a-f0-9]{8})$', block)
        if stage == b'returned':
            if active.decode() != home['home_window']:
                raise ValueError('keyboard workflow did not return to Home')
        elif not re.search(rb'^N00_X11_WINDOW id='+active+rb' map=2 geometry=864x480\+0\+0 pid='+pid+rb' class=6e6f746573004e6f74657300$', block, re.M):
            raise ValueError('original Notes window is not focused')
    if set(frames) != set(STAGES):
        raise ValueError('incomplete keyboard frames')
    # Magnifier residue in the transparent band must clear to the actual blank
    # Notes background. The live prediction candidate near the text is retained.
    band = (0, 440, 480, 530)
    empty_band = portrait_crop(frames['editor'], band)
    if empty_band != b'\xff' * len(empty_band):
        raise ValueError('unexpected empty Notes background in popup band')
    for stage in ('typed','deleted','symbols','again'):
        if portrait_crop(frames[stage], band) != empty_band:
            raise ValueError('keyboard key magnifier left stale pixels: '+stage)
    keyboard_box = (0, 550, 480, 864)
    crops = {stage: portrait_crop(frame, keyboard_box) for stage,frame in frames.items()}
    different = lambda a,b: sum(a[i:i+3] != b[i:i+3] for i in range(0,len(a),3))
    layout_hashes = {stage:hashlib.sha256(crops[stage]).hexdigest() for stage in LAYOUT_RGB}
    if layout_hashes != LAYOUT_RGB:
        raise ValueError('original uppercase, lowercase, symbol or reopened keyboard pixels changed')
    if different(crops['editor'], crops['empty']) < 50000 or different(crops['symbols'], crops['saved']) < 50000:
        raise ValueError('keyboard show, symbol switch or hide had no material effect')
    return {'notes_pid':int(notes_pid), 'saved_text':'Qemu', 'database_read_only':True,
            'same_instance':True, 'key_magnifier_residue_pixels':0, 'layout_rgb_sha256':layout_hashes, 'stages':list(STAGES)}


def run_probe(qmp, serial, wait_line, capture, display, rotation, out, drain, framebuffer):
    recorder = motion.Recorder(qmp,out,drain,framebuffer)
    try:
        return _run_probe(qmp,serial,wait_line,capture,display,rotation,out,drain,framebuffer,recorder)
    finally:
        recorder.save()


def _run_probe(qmp, serial, wait_line, capture, display, rotation, out, drain, framebuffer, recorder):
    if rotation != 270:
        raise ValueError('keyboard probe requires upright portrait')
    measurements = []
    idle_cpu = {}
    def command(text, marker):
        serial.sendall((text + f"; printf '\\n{marker}\\n'\n").encode())
        wait_line(marker.encode())
    def wait(seconds):
        recorder.wait(seconds)
    def pointer(x,y,down):
        qmp.call('input-send-event', {'events':[
            {'type':'abs','data':{'axis':'x','value':round(x*32767/479)}},
            {'type':'abs','data':{'axis':'y','value':round(y*32767/863)}},
            {'type':'btn','data':{'button':'left','down':down}}]})
    def tap(x,y):
        pointer(x,y,True); wait(.12); pointer(x,y,False); wait(.28)
    def idle(stage, delay):
        wait(delay)
        command(f"printf '\\nN00_GUEST_CPU_{stage}_before\\n'; sh /tmp/n00-shell-guest.sh keyboard-cpu", f'N00_GUEST_CPU_DONE_{stage}_before')
        first = framebuffer.sample_process(qmp.process.pid)
        wait(2)
        idle_cpu[stage] = framebuffer.summarize_cpu([first,framebuffer.sample_process(qmp.process.pid)])
        command(f"printf '\\nN00_GUEST_CPU_{stage}_after\\n'; sh /tmp/n00-shell-guest.sh keyboard-cpu", f'N00_GUEST_CPU_DONE_{stage}_after')
    def observe(stage, delay=1):
        wait(delay)
        recorder.finish()
        command(f"printf '\\nN00_KEYBOARD_BEGIN_{stage}\\n'; sh /tmp/n00-shell-guest.sh keyboard-inspect; "
                f"printf '\\nN00_KEYBOARD_EXIT_{stage}_%s\\n' $?", f'N00_KEYBOARD_DONE_{stage}')
        capture('keyboard-'+stage)
        print('KEYBOARD: '+stage, flush=True)
        if stage in ('empty','editor','saved','returned'):
            idle(stage, 10 if stage == 'returned' else .5)
    idle('home',10)
    probe = framebuffer.FrameProbe(qmp, out/'keyboard-timing', drain)
    command('sh /tmp/n00-shell-guest.sh keyboard-prepare', 'N00_KEYBOARD_PREPARED')
    launched = time.monotonic()
    # The actual, partially visible Notes icon in Home's sixth row. This also
    # exercises inherited MInputContext and the existing direct-invoker path.
    tap(70,827)
    while True:
        sample = probe.read()
        rgb = framebuffer.framebuffer_rgb(probe.dump.read_bytes())
        body = portrait_crop(b'P6\n864 480\n255\n'+rgb,(0,36,480,864))
        if hashlib.sha256(body).hexdigest() == 'e179504c7797c854beae23c7c4f23906be6ebe34b96a6760ba63a65f3cd12078':
            launch_seconds = sample['end']-launched
            break
        if time.monotonic()-launched > 45:
            raise ValueError('Notes did not reach its original empty frame after Home tap')
        wait(.05)
    observe('empty')
    recorder.begin('show')
    tap(240,827); observe('editor', 5)
    def text_region():
        sample = probe.read()
        rgb = framebuffer.framebuffer_rgb(probe.dump.read_bytes())
        return sample, portrait_crop(b'P6\n864 480\n255\n'+rgb, (10,160,450,208))
    for label,x,y in (('Q',24,590),('e',119,590),('m',384,750),('u',312,590),('x',144,750),('Backspace',449,750)):
        if label == 'Backspace': observe('typed')
        _, before = text_region()
        started = time.monotonic()
        pointer(x,y,True); wait(.12); pointer(x,y,False)
        observed = None
        while time.monotonic()-started < 5:
            sample, pixels = text_region()
            changed = sum(before[i:i+3] != pixels[i:i+3] for i in range(0,len(pixels),3))
            if changed >= 70:
                observed = {'key':label, 'seconds':sample['end']-started, 'text_region_changed_pixels':changed}
                break
            wait(.025)
        if observed is None:
            raise ValueError('no observed text response to '+label)
        measurements.append(observed)
        wait(.28)
    observe('deleted')
    tap(55,825); observe('symbols')
    recorder.begin('hide-save')
    tap(384,70); observe('saved',3)
    recorder.begin('show-again')
    tap(240,827); observe('again',3)
    recorder.begin('hide-cancel')
    tap(90,70); wait(2)
    recorder.finish()
    capture('keyboard-cancelled')
    pointer(0,420,True)
    for i in range(1,21): wait(.05); pointer(i*21,420,True)
    pointer(420,420,False)
    observe('returned',5)
    result = {'scope':'QMP press to first changed guest RAM text region; includes 120 ms press and sampling overhead; not display latency or FPS',
              'notes_home_tap_to_empty_seconds':launch_seconds,
              'text_response':measurements, 'idle_cpu':idle_cpu}
    (out/'keyboard-timing.json').write_text(json.dumps(result,indent=2)+'\n')
    return result
