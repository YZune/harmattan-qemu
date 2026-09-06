#!/usr/bin/env python3
"""Capture actual PR1.3 shell startup failures; not a desktop acceptance test."""
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import select
import signal
import socket
import subprocess
import time

SPEC = importlib.util.spec_from_file_location("display_smoke", Path(__file__).with_name("smoke-arm64-display.py"))
display = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(display)
XORG_SPEC = importlib.util.spec_from_file_location("xorg_smoke", Path(__file__).with_name("smoke-arm64-xorg.py"))
xorg = importlib.util.module_from_spec(XORG_SPEC)
XORG_SPEC.loader.exec_module(xorg)
CALC_SPEC = importlib.util.spec_from_file_location("calculator_smoke", Path(__file__).with_name("smoke-arm64-calculator.py"))
calculator = importlib.util.module_from_spec(CALC_SPEC)
CALC_SPEC.loader.exec_module(calculator)
POSE_SPEC = importlib.util.spec_from_file_location("orientation", Path(__file__).with_name("arm64-orientation.py"))
orientation = importlib.util.module_from_spec(POSE_SPEC)
POSE_SPEC.loader.exec_module(orientation)
SYSTEMUI_SPEC = importlib.util.spec_from_file_location("systemui", Path(__file__).with_name("arm64-systemui.py"))
systemui = importlib.util.module_from_spec(SYSTEMUI_SPEC)
SYSTEMUI_SPEC.loader.exec_module(systemui)
CLOCK_SPEC = importlib.util.spec_from_file_location("guest_clock", Path(__file__).with_name("arm64-clock.py"))
guest_clock = importlib.util.module_from_spec(CLOCK_SPEC)
CLOCK_SPEC.loader.exec_module(guest_clock)
ANIMATION_SPEC = importlib.util.spec_from_file_location("animations", Path(__file__).with_name("arm64-animations.py"))
animations = importlib.util.module_from_spec(ANIMATION_SPEC)
ANIMATION_SPEC.loader.exec_module(animations)
SPLASH_SPEC = importlib.util.spec_from_file_location("splash", Path(__file__).with_name("arm64-splash.py"))
splash = importlib.util.module_from_spec(SPLASH_SPEC)
SPLASH_SPEC.loader.exec_module(splash)
STARTUP_SPEC = importlib.util.spec_from_file_location("startup", Path(__file__).with_name("arm64-startup.py"))
startup = importlib.util.module_from_spec(STARTUP_SPEC)
STARTUP_SPEC.loader.exec_module(startup)
BOOT_SPEC = importlib.util.spec_from_file_location("boot_animation", Path(__file__).with_name("arm64-boot-animation.py"))
boot_animation = importlib.util.module_from_spec(BOOT_SPEC)
BOOT_SPEC.loader.exec_module(boot_animation)
TRANSITION_SPEC = importlib.util.spec_from_file_location("transitions", Path(__file__).with_name("probe-arm64-transitions.py"))
transitions = importlib.util.module_from_spec(TRANSITION_SPEC)
TRANSITION_SPEC.loader.exec_module(transitions)
PERF_NAME = 'measure-arm64-interaction.py' if os.environ.get('HARMATTAN_UI_INTERACTION_PROBE') == '1' else 'measure-arm64-ui.py'
PERF_SPEC = importlib.util.spec_from_file_location("ui_performance", Path(__file__).with_name(PERF_NAME))
performance = importlib.util.module_from_spec(PERF_SPEC)
PERF_SPEC.loader.exec_module(performance)
KEYBOARD_SPEC = importlib.util.spec_from_file_location('keyboard', Path(__file__).with_name('arm64-keyboard.py'))
keyboard = importlib.util.module_from_spec(KEYBOARD_SPEC)
KEYBOARD_SPEC.loader.exec_module(keyboard)
NETWORK_SPEC = importlib.util.spec_from_file_location('network', Path(__file__).with_name('arm64-network.py'))
network = importlib.util.module_from_spec(NETWORK_SPEC)
NETWORK_SPEC.loader.exec_module(network)
STORAGE_SPEC = importlib.util.spec_from_file_location('storage', Path(__file__).with_name('arm64-storage.py'))
storage = importlib.util.module_from_spec(STORAGE_SPEC)
STORAGE_SPEC.loader.exec_module(storage)
AUDIO_SPEC = importlib.util.spec_from_file_location('audio', Path(__file__).with_name('arm64-audio.py'))
audio = importlib.util.module_from_spec(AUDIO_SPEC)
AUDIO_SPEC.loader.exec_module(audio)
READINESS_SPEC = importlib.util.spec_from_file_location('readiness', Path(__file__).with_name('arm64-readiness.py'))
readiness = importlib.util.module_from_spec(READINESS_SPEC)
READINESS_SPEC.loader.exec_module(readiness)
PHASES = ("bootstrap", "theme", "compositor", "home", "settled", "final")
LIBRARIES = {
    "/usr/bin/mcompositor": "52d29f7f90d03277ded463ebc3c5f33d",
    "/usr/bin/meegotouchhome": "f1baf59a510e9896e74ee4e5b7cde63c",
    "/usr/lib/libEGL.so.1": "2d33b733564f1adf8d2978f6e74efde2",
    "/usr/lib/libGLESv2.so.1": "061a075a2191fd79abd43640851c60b2",
    "/usr/lib/libEGL.so": "2d33b733564f1adf8d2978f6e74efde2",
    "/usr/lib/libGLESv2.so": "061a075a2191fd79abd43640851c60b2",
}


def validate_desktop_serial(data, with_input=False):
    data = data.replace(b"\r", b"")
    blocks = {}
    for phase in PHASES:
        begin = f"N00_SHELL_BEGIN_{phase}".encode()
        end = f"N00_SHELL_PHASE_{phase}_0".encode()
        lines = data.split(b"\n")[:-1]
        if lines.count(begin) != 1 or lines.count(end) != 1:
            raise ValueError("missing unique completed shell phase")
        matches = re.findall(rb"(?:^|\n)" + begin + rb"\n(.*?)\n" + end + rb"\n", data, re.DOTALL)
        if len(matches) != 1:
            raise ValueError("invalid shell phase boundaries")
        blocks[phase] = matches[0] + b"\n"
    for name, digest in LIBRARIES.items():
        matches = re.findall(rb"([0-9a-f]{32})  " + re.escape(name.encode()) + rb"\n", blocks["bootstrap"])
        if matches != [digest.encode()]:
            raise ValueError("original shell executable/library identity mismatch")
    if with_input:
        if len(re.findall(rb'^N00_SHELL_INPUT_REAL /dev/input/event\d+$', data, re.MULTILINE)) != 1 or b'N00_SHELL_INPUT_NOT_IMPLEMENTED' in data:
            raise ValueError("missing real input device")
        for capability in (b'mtev: caps: mtdata touch_major tracking_id position_x position_y',
                           b'mtev: position_x: 0 863', b'mtev: position_y: 0 479'):
            if capability not in data:
                raise ValueError("Xorg did not initialize the real MXT input axes")
    elif data.split(b"\n").count(b"N00_SHELL_INPUT_NOT_IMPLEMENTED") != 1:
        raise ValueError("input limitation must remain explicit")
    if any(error in data for error in (b"Fatal server error", b"X Error of failed request", b"Segmentation fault", b"std::bad_alloc")):
        raise ValueError("Xorg or shell process failure")
    errors = re.findall(rb"^(?:\[\s*\d+\.\d+\]\s+)?\(EE\) ([^\n]+)", data, re.MULTILINE)
    if any(error not in xorg.INPUT_ERRORS for error in errors):
        raise ValueError("unexpected Xorg error")
    if with_input and any(any(name in error for name in (b'mtev', b'Touchscreen', b'qemu-touchscreen')) for error in errors):
        raise ValueError("real touchscreen initialization failed")
    observations = []
    for phase in ("home", "settled"):
        block = blocks[phase]
        pids = {}
        for name, uid in (("Xorg", 0), ("mthemedaemon", 29999), ("mcompositor", 29999), ("meegotouchhome", 29999)):
            records = re.findall(rb"N00_SHELL_PROCESS " + name.encode() + rb" (\d+)\nName:\s*" + name.encode() +
                                 rb"\nState:\s*([RS])[^\n]*\nTgid:\s*(\d+)\nPid:\s*(\d+)\nPPid:[^\n]*\nTracerPid:\s*0\nUid:\s*(\d+)\s+\d+\s+\d+\s+\d+\n", block)
            if len(records) != 1:
                raise ValueError("shell process missing, stopped or traced")
            pid, state, tgid, actual_pid, actual_uid = records[0]
            if pid != tgid or pid != actual_pid or int(actual_uid) != uid:
                raise ValueError("shell process identity mismatch")
            pids[name] = int(pid)
        if len(re.findall(rb"^N00_X11_ROOT id=[0-9a-f]{8} size=864x480 depth=24$", block, re.MULTILINE)) != 1:
            raise ValueError("missing real X11 screen")
        managers = re.findall(rb"^N00_X11_WM check=([0-9a-f]{8}) self=([0-9a-f]{8})$", block, re.MULTILINE)
        owners = re.findall(rb"^N00_X11_COMPOSITOR owner=([0-9a-f]{8})$", block, re.MULTILINE)
        if len(managers) != 1 or len(owners) != 1 or int(owners[0], 16) == 0 or managers[0] != (owners[0], owners[0]):
            raise ValueError("WM check and compositor selection do not agree")
        clients = re.findall(rb"^N00_X11_CLIENTS ([0-9a-f,]+)$", block, re.MULTILINE)
        if len(clients) != 1:
            raise ValueError("missing managed client list")
        home_class = b"meegotouchhome\0Meegotouchhome\0".hex().encode()
        windows = re.findall(rb"^N00_X11_WINDOW id=([0-9a-f]{8}) map=2 geometry=864x480\+0\+0 pid=" +
                             str(pids["meegotouchhome"]).encode() + rb" class=" + home_class + rb"$", block, re.MULTILINE)
        if len(windows) != 1 or windows[0] not in clients[0].split(b",") or block.split(b"\n").count(b"N00_X11_INSPECT_OK") != 1:
            raise ValueError("actual Home window is not mapped and managed")
        observations.append({"pids": pids, "home_window": windows[0].decode(), "wm_window": owners[0].decode()})
    if observations[0] != observations[1]:
        raise ValueError("shell restarted or changed identity during observation")
    return {**observations[0], "runtime_md5": LIBRARIES,
            "known_input_errors": sorted(set(error.decode() for error in errors))}


def validate_scroll(data, home, initial, scrolled, restored):
    data = data.replace(b'\r', b'')
    for step in (1, 2):
        begin, end = f'N00_INPUT_SCROLL_{step}'.encode(), f'N00_INPUT_SCROLL_DONE_{step}'.encode()
        lines = data.split(b'\n')[:-1]
        if lines.count(begin) != 1 or lines.count(end) != 1:
            raise ValueError('missing or duplicated scroll observation')
        blocks = re.findall(rb'(?:^|\n)' + begin + rb'\n(.*?)\n' + end + rb'\n', data, re.DOTALL)
        if len(blocks) != 1:
            raise ValueError('invalid scroll observation boundaries')
        block = blocks[0]
        identity = (f"N00_X11_WINDOW id={home['home_window']} map=2 geometry=864x480+0+0 pid={home['pids']['meegotouchhome']} class=".encode()
                    + b'meegotouchhome\0Meegotouchhome\0'.hex().encode())
        manager = f"N00_X11_WM check={home['wm_window']} self={home['wm_window']}".encode()
        owner = f"N00_X11_COMPOSITOR owner={home['wm_window']}".encode()
        if any(block.split(b'\n').count(marker) != 1 for marker in (identity, manager, owner, b'N00_X11_INSPECT_OK')):
            raise ValueError('Home identity or compositor changed during scroll')
        clients = re.findall(rb'^N00_X11_CLIENTS ([0-9a-f,]+)$', block, re.MULTILINE)
        if len(clients) != 1 or home['home_window'].encode() not in clients[0].split(b','):
            raise ValueError('Home is not managed after scrolling')
    before, after, back = map(desktop_frame, (initial, scrolled, restored))
    if before != back:
        raise ValueError('reverse drag did not restore the initial Home pixels')
    header = len(b'P6\n864 480\n255\n')
    a, b = initial[header:], scrolled[header:]
    changed = sum(a[i:i + 3] != b[i:i + 3] for i in range(0, len(a), 3))
    if changed < 50000:
        raise ValueError('drag did not materially change Home content')
    return {'changed_pixels': changed, 'initial': before, 'scrolled': after,
            'restored': back, 'round_trip_exact': True}


def validate_desktop_host(data):
    lines = data.strip().split(b"\n")
    if len(lines) != 10:
        raise ValueError("unexpected shell GPU log")
    expected = {0: b"N00_GLES connect client=0 abi=1", 1: b"N00_GLES connect client=1 abi=2",
                3: b"N00_GLES connect client=2 abi=2", 5: b"N00_GLES disconnect client=1",
                6: b"N00_GLES disconnect client=2", 7: b"N00_GLES disconnect client=0"}
    if any(lines[index] != value for index, value in expected.items()):
        raise ValueError("unexpected shell client/worker lifecycle")
    for index, client in ((2, 1), (4, 2)):
        if not re.fullmatch(f"N00_GLES current client={client} es=2 renderer=Apple ".encode() + rb"[^\n]+", lines[index]):
            raise ValueError("missing actual Apple GPU context")
    render = re.fullmatch(rb"N00_GLES render compiles=(\d+) links=(\d+) uploads=(\d+) draws=(\d+) rejects=0", lines[8])
    summary = re.fullmatch(rb"N00_GLES summary calls=(\d+) swaps=(\d+) faults=0 workers=joined", lines[9])
    if not render or not summary or not all(int(value) > 0 for value in (*render.groups(), *summary.groups())):
        raise ValueError("missing rendering, rejected calls or incomplete worker exit")
    return dict(zip(("compiles", "links", "uploads", "draws", "calls", "swaps"),
                    map(int, (*render.groups(), *summary.groups()))), rejects=0, faults=0, workers_joined=True)


def validate_live_host(data):
    lines = data.strip().split(b'\n')
    if len(lines) != 5 or lines[0] != b'N00_GLES connect client=0 abi=1' or \
            lines[1] != b'N00_GLES connect client=1 abi=2' or lines[3] != b'N00_GLES connect client=2 abi=2':
        raise ValueError('unexpected native-window startup log; inspect qemu-stderr.log')
    for index, client in ((2, 1), (4, 2)):
        if not re.fullmatch(f'N00_GLES current client={client} es=2 renderer=Apple '.encode() + rb'[^\n]+', lines[index]):
            raise ValueError('missing native GPU context at startup')
    return {'gpu_contexts': 2, 'shutdown_summary_pending': True}


def desktop_frame(data):
    header = b"P6\n864 480\n255\n"
    if not data.startswith(header) or len(data) != len(header) + 864 * 480 * 3:
        raise ValueError("wrong desktop framebuffer dimensions or length")
    rgb = data[len(header):]
    colors = Counter(zip(rgb[::3], rgb[1::3], rgb[2::3]))
    non_black = 864 * 480 - colors[(0, 0, 0)]
    # This excludes black/few-colour probes, not a semantic image-recognition test.
    # Actual Home identity is independently checked above and PNGs are reviewed.
    if len(colors) < 4096 or non_black < 50000:
        raise ValueError("empty or simple test-pattern framebuffer")
    return {"rgb_sha256": hashlib.sha256(rgb).hexdigest(), "colors": len(colors), "non_black_pixels": non_black}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network", choices=("off", "user"), default="off")
    parser.add_argument('--audio', choices=('off', 'pulse'), default='off')
    parser.add_argument('--startup-waits', choices=('fixed', 'ready'), default='fixed')
    parser.add_argument('--profile', type=Path, help='private persistent disk directory; interactive mode only')
    parser.add_argument('--profile-base', type=Path, help='launcher-created private raw clone')
    parser.add_argument('--profile-image-tool', type=Path, help='matching qemu-img executable')
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--verify-desktop", action="store_true", help="require mapped Home, WM ownership and stable nonempty rendering; not input")
    parser.add_argument("--exercise-input", action="store_true", help="diagnose real MXT scroll input after desktop settles")
    parser.add_argument("--verify-input", action="store_true", help="require real Xorg MXT input, changed Home pixels and exact drag restoration")
    parser.add_argument("--rotation", type=int, choices=(0, 90, 180, 270), default=0)
    parser.add_argument("--interactive", action="store_true", help="validate startup, then keep the native window running until closed")
    parser.add_argument('--exit-on-ready', action='store_true', help='bounded startup diagnostic using the interactive readiness gates')
    parser.add_argument('--boot-animation', type=Path, help='private raw clone containing the original boot movie; interactive Cocoa only')
    parser.add_argument("--device-orientation", choices=('display', 'disabled', 'top', 'left', 'bottom', 'right'),
                        help="virtual ContextKit pose; default follows display in interactive mode, disabled in historical diagnostics")
    parser.add_argument("--exercise-orientation", action="store_true", help="Calendar portrait/landscape/portrait and Home regression")
    parser.add_argument("--system-ui", choices=('on', 'off'), help="original statusbar provider; on by default for interactive use, off in historical diagnostics")
    parser.add_argument("--clock", choices=('host', 'off'), help="synchronize host UTC and local timezone; defaults to host with System UI, otherwise off")
    parser.add_argument('--input-method', choices=('on', 'off'), help='original Maliit keyboard; defaults on for interactive use')
    parser.add_argument('--exercise-keyboard', action='store_true', help='original Notes typing, deletion, symbol layout, save and reopen before Calculator regression')
    parser.add_argument("--compositor-animations", choices=('on', 'off'), help="process-local matrix correction; on by default for interactive use, off in historical diagnostics")
    parser.add_argument('--display-handoff', choices=('on', 'off'), help='opt-in real-pixel overlay handoff; currently requires splash off')
    parser.add_argument("--splash", choices=('on', 'off'), help="experimental original launch-splash protocol; off by default pending compositor regression")
    parser.add_argument("--exercise-startup-input", action="store_true", help="discard early MXT clicks, then run normal Calculator input after startup release")
    parser.add_argument("--exercise-calculator", action="store_true", help="diagnose a real Home tap launching Calculator; not app acceptance")
    parser.add_argument("--exercise-transitions", action="store_true", help="sample app open/return/resume intermediate RAM frames; not display FPS")
    parser.add_argument("--measure-performance", action="store_true", help="bounded CPU and guest framebuffer observations using the Calculator workflow; not FPS")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.exit_on_ready and (not args.interactive or args.profile or args.boot_animation):
        parser.error('bounded startup requires interactive readiness with an independent snapshot and no boot movie')
    if args.profile and (not args.interactive or not args.profile_base or not args.profile_image_tool):
        parser.error('profiles require interactive mode and the launcher\'s private base/image tool')
    if not args.profile and (args.profile_base or args.profile_image_tool):
        parser.error('profile inputs require a profile directory')
    if args.boot_animation and not args.interactive:
        parser.error('boot presentation is only used by interactive Cocoa startup')
    if args.exercise_keyboard and (args.interactive or args.rotation != 270 or args.measure_performance or not args.exercise_transitions):
        parser.error('keyboard regression requires its own upright transition diagnostic')
    if args.exercise_startup_input:
        if args.interactive or args.exercise_calculator or args.exercise_transitions or args.exercise_orientation or args.measure_performance or args.rotation != 270:
            parser.error('startup input regression requires its own 270-degree Calculator sequence')
        args.exercise_calculator = True
    if args.exercise_transitions:
        if args.exercise_calculator or args.measure_performance or args.exercise_orientation or args.rotation != 270:
            parser.error('transition diagnosis requires its own 270-degree Calculator input sequence')
        args.exercise_calculator = True
    if args.measure_performance:
        if args.exercise_calculator:
            parser.error('choose either Calculator diagnosis or performance measurement')
        args.exercise_calculator = True
    if args.exercise_calculator and (args.interactive or args.exercise_input or args.verify_input or args.verify_desktop):
        parser.error('calculator diagnosis uses its own input sequence')
    if args.interactive and (args.exercise_input or args.verify_input or args.verify_desktop):
        parser.error('interactive mode does not inject automatic test gestures')
    if args.verify_input:
        args.exercise_input = True
    if args.verify_desktop and args.exercise_input:
        parser.error('use --verify-input for the input profile, not --verify-desktop')
    if args.exercise_orientation:
        if args.interactive or args.measure_performance or args.exercise_input or args.verify_desktop or args.rotation != 270:
            parser.error('orientation regression requires its own 270-degree input sequence')
        if args.device_orientation not in (None, 'display', 'left'):
            parser.error('orientation regression starts in upright display orientation')
        args.device_orientation = 'display'
    edge = orientation.select_edge(args.device_orientation, args.interactive, args.rotation)
    systemui_on = systemui.enabled(args.system_ui, args.interactive)
    keyboard_on = systemui.enabled(args.input_method, args.interactive)
    if keyboard_on and (not systemui_on or args.measure_performance):
        parser.error('keyboard requires original System UI and a separate non-performance regression')
    if args.exercise_keyboard and not keyboard_on:
        parser.error('keyboard regression requires the original input method')
    if args.exercise_startup_input and not systemui_on:
        parser.error('startup input regression requires original System UI')
    animations_on = animations.enabled(args.compositor_animations, args.interactive)
    splash_on = splash.enabled(args.splash, args.interactive)
    handoff_on = args.display_handoff == 'on'
    if handoff_on and (not animations_on or splash_on):
        parser.error('display handoff requires compositor animations on and splash off')
    if splash_on and (not animations_on or args.measure_performance):
        parser.error('splash requires animation adaptation and a separate non-performance regression')
    if animations_on and (not systemui_on or args.measure_performance):
        parser.error('animation adaptation requires System UI and a separate non-performance regression')
    if systemui_on and args.measure_performance:
        parser.error('System UI requires its own non-performance regression; historical performance baselines are unchanged')
    host_validator = systemui.validate_host if systemui_on else validate_desktop_host
    ui_service = {'enabled': systemui_on}
    if systemui_on:
        ui_service['validator_sha256'] = hashlib.sha256(Path(systemui.__file__).read_bytes()).hexdigest()
    clock_mode = args.clock or ('host' if systemui_on else 'off')
    clock_on = guest_clock.enabled(clock_mode)
    clock_info = {'enabled': clock_on, 'mode': clock_mode}
    timezone_payload = None
    if clock_on:
        timezone_payload, metadata = guest_clock.prepare()
        clock_info.update(metadata)
        clock_info['validator_sha256'] = hashlib.sha256(Path(guest_clock.__file__).read_bytes()).hexdigest()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command or "-snapshot" not in command or args.timeout <= 0:
        parser.error("a positive timeout and QEMU -snapshot are required")
    pose = {'enabled': edge is not None}
    if edge is not None:
        pose_binary, pose_script, pose_info = orientation.prepare()
        pose.update(pose_info, mode=args.device_orientation or 'display', edge=edge)
    animation_info = {'enabled': animations_on}
    if animations_on:
        animation_binary, metadata = animations.prepare(splash=splash_on, handoff=handoff_on)
        animation_info.update(metadata)
    splash_info = {'enabled': splash_on}
    helper_payloads = {}
    keyboard_info = {'enabled': keyboard_on}
    if keyboard_on:
        keyboard_payloads, metadata = keyboard.prepare(exercise=args.exercise_keyboard)
        helper_payloads.update(keyboard_payloads)
        keyboard_info.update(metadata)
    if splash_on:
        splash_payloads, metadata = splash.prepare()
        helper_payloads.update(splash_payloads)
        splash_info.update(metadata)
    guard_on = args.interactive or args.exercise_startup_input
    guard_info = {'enabled': guard_on}
    if guard_on:
        guard_payloads, metadata = startup.prepare()
        helper_payloads.update(guard_payloads)
        guard_info.update(metadata)
    if args.startup_waits == 'ready':
        for name in ('N00X11.pm', 'wait-shell-ready-guest.pl'):
            helper_payloads[name] = Path(__file__).with_name(name).read_bytes()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    boot_info = {'enabled': False}
    boot_environment = {}
    if args.boot_animation:
        boot_environment, boot_info = boot_animation.prepare(args.boot_animation, out / 'boot', args.rotation)
    guest = Path(__file__).with_name("diagnose-shell-guest.sh").read_bytes()
    inspector = Path(__file__).with_name("inspect-shell-x11.pl").read_bytes()
    qemu_digest = hashlib.sha256(Path(command[0]).read_bytes()).hexdigest()
    runner_digest = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    calculator_digest = hashlib.sha256(Path(calculator.__file__).read_bytes()).hexdigest()
    performance_digest = hashlib.sha256(Path(performance.__file__).read_bytes()).hexdigest()
    timings = {}
    measurements = None
    started = time.monotonic()
    deadline = started + args.timeout
    serial, child = socket.socketpair()
    process = None
    profile_session = None
    profile_synced = False
    audio_output = None
    shutdown_request = out / 'storage-shutdown.request'
    phases = {}
    control = []
    if args.interactive or args.measure_performance:
        control_path = str(out / 'control.sock')
        if len(os.fsencode(control_path)) >= 104:
            parser.error('workspace path too long for the local QMP socket')
        control = ['-qmp', f'unix:{control_path},server=on,wait=off']

    def raw_frame(name):
        return display.native_ppm((out / f'{name}.ppm').read_bytes(), args.rotation)

    try:
        if args.audio == 'pulse':
            if args.network != 'user':
                raise ValueError('PulseAudio output requires SDK Ethernet')
            audio_output = audio.Output(out / 'audio')
        if args.profile:
            profile_session = storage.Profile(args.profile, args.profile_base, args.profile_image_tool)
            command = storage.persistent_command(command, profile_session.disk)
            boot_environment['N00_COCOA_STORAGE_SHUTDOWN'] = str(shutdown_request)
        with (out / "serial.log").open("xb") as log, (out / "qemu-stderr.log").open("xb") as errors:
            process = subprocess.Popen(command + control + ["-qmp", "stdio", "-chardev",
                f"socket,id=n00serial,fd={child.fileno()}", "-serial", "chardev:n00serial", "-monitor", "none"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors,
                env=display.qemu_environment() | boot_environment,
                pass_fds=(child.fileno(),) + ((profile_session.fd,) if profile_session else ()), bufsize=0)
            child.close()
            qmp = display.QMP(process, deadline)

            def drain(seconds):
                end = time.monotonic() + seconds
                first = True
                while first or time.monotonic() < end:
                    first = False
                    if process.poll() is not None:
                        raise RuntimeError('QEMU exited during performance observation')
                    if select.select([serial], [], [], min(0.2, max(0, end - time.monotonic())))[0]:
                        chunk = serial.recv(65536)
                        if not chunk:
                            raise RuntimeError('QEMU serial closed during measurement')
                        log.write(chunk); log.flush()
                        if any(marker in chunk for marker in display.FATAL):
                            raise RuntimeError('guest failure during performance measurement')

            def capture(name):
                # Freeze guest execution for a consistent PPM/PNG pair. Avoid
                # resuming vCPUs inside a display-update coroutine nested in
                # the legacy synchronous MMC/DMA path. Rendering/input between
                # captures remains live; this does not repair MMC concurrency.
                qmp.call('stop')
                try:
                    for ext in ('ppm', 'png'):
                        qmp.call('screendump', {'filename': str(out / f'{name}.{ext}'), 'format': ext})
                finally:
                    qmp.call('cont')

            def wait_line(marker):
                if marker in (out / "serial.log").read_bytes().replace(b"\r", b"").split(b"\n")[:-1]:
                    return
                display.wait_serial(serial, process, log,
                    lambda data: marker in data.split(b"\n")[:-1], deadline)

            display.wait_serial(serial, process, log,
                lambda data: b"shell ready" in data and b"/ # " in data, deadline)
            timings['boot_to_serial_shell_seconds'] = time.monotonic() - started
            serial.sendall(b"dmesg -n 1; stty -echo; PS2=''; printf '\\nN00_SHELL_UPLOAD_READY\\n'\n")
            wait_line(b"N00_SHELL_UPLOAD_READY")
            if os.environ.get('HARMATTAN_UI_IDLE_PROFILE', '').startswith('wfi'):
                # The original UART driver ignores RX during the first jiffy
                # after its sleep timeout. A host serial burst can therefore
                # lose a command prefix. Keep only the diagnostic UART awake;
                # CPU WFI remains enabled. The setting is snapshot-local.
                serial.sendall(b"test -f /sys/devices/platform/serial8250.2/sleep_timeout && "
                    b"printf '0\\n' > /sys/devices/platform/serial8250.2/sleep_timeout && "
                    b"test \"$(cat /sys/devices/platform/serial8250.2/sleep_timeout)\" = 0 && "
                    b"printf '\\nN00_IDLE_UART_AWAKE\\n'\n")
                wait_line(b'N00_IDLE_UART_AWAKE')
            if profile_session:
                storage.prepare_guest(serial, process, log, display)
            if args.network == 'user':
                network_result = network.configure(serial, process, log, deadline, display)
                (out / 'network-result.json').write_text(json.dumps(network_result, indent=2) + '\n')
            def upload(payload, target, tag):
                serial.sendall(f"/usr/bin/perl -ne 'chomp; print pack(\"H*\",$_)' > {target} <<'{tag}'\n".encode())
                encoded = payload.hex()
                for start in range(0, len(encoded), 76):
                    serial.sendall(encoded[start:start + 76].encode() + b"\n")
                serial.sendall(f"{tag}\nprintf '\\n{tag}_DONE\\n'\n".encode())
                wait_line(f"{tag}_DONE".encode())

            upload(guest, "/tmp/n00-shell-guest.sh", "N00_SHELL_SCRIPT")
            upload(inspector, "/tmp/n00-shell-x11.pl", "N00_SHELL_INSPECTOR")
            if audio_output:
                upload(audio_output.cookie, '/tmp/n00-audio.cookie', 'N00_AUDIO_COOKIE')
                serial.sendall(b'chown user /tmp/n00-audio.cookie && chmod 0600 /tmp/n00-audio.cookie\n')
                serial.sendall(f'export N00_UI_AUDIO_SERVER={audio_output.guest_server}\n'.encode())
            clock_snapshot = None
            if clock_on:
                upload(timezone_payload, guest_clock.GUEST_TIMEZONE, "N00_CLOCK_TIMEZONE")
                clock_snapshot = guest_clock.snapshot()
                serial.sendall(guest_clock.guest_sync_command(clock_snapshot, clock_info['timezone_md5']))
                wait_line(b'N00_CLOCK_SYNC_FINISHED')
                guest_clock.validate_sync((out / 'serial.log').read_bytes(), clock_snapshot['epoch'],
                                          clock_info['timezone_md5'])
                clock_info.update(sync_requested_epoch=clock_snapshot['epoch'],
                                  sync_requested_utc=clock_snapshot['utc'])
            if helper_payloads:
                serial.sendall(b'mkdir -m 0755 /tmp/n00-ui-helpers\n')
                for index, (name, payload) in enumerate(helper_payloads.items()):
                    upload(payload, f'{splash.HELPER_ROOT}/{name}', f'N00_SPLASH_UPLOAD_{index}')
            if splash_on:
                serial.sendall(b'export N00_UI_SPLASH=1\n')
            if guard_on:
                serial.sendall(b'export N00_UI_STARTUP_GUARD=1\n')
            if args.startup_waits == 'ready':
                serial.sendall(b'export N00_UI_READY_WAITS=1\n')
            if systemui_on:
                serial.sendall(b'export N00_UI_SYSTEMUI=1\n')
            if keyboard_on:
                serial.sendall(b'export N00_UI_KEYBOARD=1\n')
            if animations_on:
                upload(animation_binary, animations.HELPER, 'N00_ANIMATION_BINARY')
                serial.sendall(b'export N00_UI_ANIMATIONS=1\n')
            if edge is not None:
                upload(pose_binary, '/tmp/n00-orientation-provider', 'N00_POSE_BINARY')
                upload(pose_script, '/tmp/n00-orientation-guest.sh', 'N00_POSE_SCRIPT')
                serial.sendall(f'export N00_UI_TOP_EDGE={edge}\n'.encode())
            if args.exercise_input or args.interactive or args.exercise_calculator or args.exercise_orientation:
                serial.sendall(b"export N00_SHELL_INPUT=1\n")
            for phase in PHASES:
                phase_started = time.monotonic()
                if phase == 'home' and args.boot_animation:
                    boot_animation.signal(out / 'boot', 'play')
                phase_command = phase
                if phase == 'home' and args.startup_waits == 'ready':
                    serial.sendall(b"sh /tmp/n00-shell-guest.sh home-start; printf '\\nN00_HOME_START_EXIT_%s\\n' $?; printf 'N00_HOME_START_DONE\\n'\n")
                    wait_line(b'N00_HOME_START_DONE')
                    if re.findall(rb'^N00_HOME_START_EXIT_(\d+)$', (out / 'serial.log').read_bytes().replace(b'\r', b''), re.M) != [b'0']:
                        raise ValueError('original Home did not finish window initialization')
                    def observe_home():
                        capture('home-readiness')
                        return raw_frame('home-readiness')
                    timings['home_settle'] = readiness.settle(observe_home,
                        lambda a, b: guest_clock.compare_home_frames(a, b, systemui_on and clock_on)['content_equal'],
                        desktop_frame, drain)
                    phase_command = 'home-report'
                serial.sendall(f"printf '\\nN00_SHELL_BEGIN_{phase}\\n'; sh /tmp/n00-shell-guest.sh {phase_command}; printf '\\nN00_SHELL_PHASE_{phase}_%s\\n' $?\n".encode())
                pattern = rb"(?:^|\n)N00_SHELL_PHASE_" + phase.encode() + rb"_(\d+)\n"
                if args.measure_performance and phase == 'home':
                    probe = performance.FrameProbe(qmp, out / 'startup-probe', drain)
                    timings['home_command_to_reference_frame'] = probe.wait_for(performance.HOME_RGB, phase_started)
                    timings['boot_to_observed_home_seconds'] = time.monotonic() - started
                    timings['startup_scope'] = 'diagnostic launcher; includes its compositor wait and earlier captures, not production cold-start performance'
                if re.search(pattern, (out / 'serial.log').read_bytes().replace(b'\r', b'')) is None:
                    display.wait_serial(serial, process, log,
                        lambda data: re.search(pattern, data) is not None, deadline)
                serial_data = (out / "serial.log").read_bytes().replace(b"\r", b"")
                status = int(re.findall(pattern, serial_data)[-1])
                phases[phase] = {"exit": status, "wall_seconds": round(time.monotonic() - phase_started, 3)}
                capture(phase)
                print(f"DIAGNOSTIC: {phase} exit={status}; screenshot: {out / (phase + '.png')}", flush=True)
                if phase == 'home' and args.exercise_startup_input:
                    startup.inject_early_clicks(qmp)
                if phase == "settled" and args.exercise_input:
                    def pointer(x, y, down):
                        x, y = display.surface_point(x, y, args.rotation)
                        width, height = (480, 864) if args.rotation in (90, 270) else (864, 480)
                        qmp.call("input-send-event", {"events": [
                            {"type": "abs", "data": {"axis": "x", "value": round(x * 32767 / (width - 1))}},
                            {"type": "abs", "data": {"axis": "y", "value": round(y * 32767 / (height - 1))}},
                            {"type": "btn", "data": {"button": "left", "down": down}},
                        ]})
                    for step, (start_x, end_x) in enumerate(((700, 200), (200, 700)), 1):
                        pointer(start_x, 240, True)
                        for offset in range(1, 21):
                            time.sleep(0.05)
                            pointer(start_x + (end_x - start_x) * offset / 20, 240, True)
                        pointer(end_x, 240, False)
                        serial.sendall(f"sleep 8; printf '\\nN00_INPUT_SCROLL_{step}\\n'; perl /tmp/n00-shell-x11.pl; printf '\\nN00_INPUT_SCROLL_DONE_{step}\\n'\n".encode())
                        wait_line(f"N00_INPUT_SCROLL_DONE_{step}".encode())
                        capture(f'scroll-{step}')
                        print(f"DIAGNOSTIC: input scroll {step}; screenshot: {out / f'scroll-{step}.png'}", flush=True)
                if phase == "bootstrap" and status:
                    break
                if phase == 'bootstrap' and edge is not None:
                    orientation.command(serial, wait_line, 'start', edge, 'startup')
                    pose['startup'] = orientation.validate_provider(
                        orientation.block((out / 'serial.log').read_bytes(), 'startup'), edge, pose['helper_md5'])
                if phase == 'theme' and systemui_on:
                    serial.sendall(b"printf '\\nN00_SYSTEMUI_START_BEGIN\\n'; sh /tmp/n00-shell-guest.sh systemui; "
                                   b"printf '\\nN00_SYSTEMUI_START_EXIT_%s\\n' $?; printf '\\nN00_SYSTEMUI_START_DONE\\n'\n")
                    wait_line(b'N00_SYSTEMUI_START_DONE')
                    startup_data = (out / 'serial.log').read_bytes().replace(b'\r', b'')
                    if re.findall(rb'^N00_SYSTEMUI_START_EXIT_(\d+)$', startup_data, re.M) != [b'0']:
                        raise ValueError('original System UI did not start')
                    ui_service['startup'] = systemui.validate_serial(startup_data, minimum_reports=1)
                if phase == 'compositor' and keyboard_on:
                    serial.sendall(b"sh /tmp/n00-shell-guest.sh input-method; printf '\\nN00_IME_START_EXIT_%s\\n' $?; printf '\\nN00_IME_START_DONE\\n'\n")
                    wait_line(b'N00_IME_START_DONE')
                    ime_data = (out/'serial.log').read_bytes().replace(b'\r',b'')
                    if re.findall(rb'^N00_IME_START_EXIT_(\d+)$', ime_data, re.M) != [b'0']:
                        raise ValueError('original input method did not start')
                    keyboard_info['startup'] = keyboard.validate_serial(ime_data, minimum_reports=1)
            if systemui_on:
                ui_service['runtime'] = systemui.validate_serial((out / 'serial.log').read_bytes())
            if keyboard_on:
                keyboard_info['runtime'] = keyboard.validate_serial((out/'serial.log').read_bytes())
            if clock_on:
                clock_info['runtime'] = guest_clock.validate_serial(
                    (out / 'serial.log').read_bytes(), clock_snapshot['epoch'], clock_info['timezone_md5'])
            if guard_on:
                guard_info['held'] = startup.validate(startup.collect(serial, wait_line, out),
                                                       exercised=args.exercise_startup_input)
            if args.exercise_startup_input:
                validate_desktop_serial((out / 'serial.log').read_bytes(), with_input=True)
                host_validator((out / 'qemu-stderr.log').read_bytes(), live=True)
                home_raw, settled_raw = raw_frame('home'), raw_frame('settled')
                desktop_frame(home_raw)
                desktop_frame(settled_raw)
                startup_frames = guest_clock.compare_home_frames(home_raw, settled_raw, systemui_on and clock_on)
                if not startup_frames['content_equal'] or any(item['exit'] for item in phases.values()):
                    raise ValueError('early input changed startup Home')
                guard_info['startup_frames'] = startup_frames
                guard_info['released'] = startup.validate(startup.collect(serial, wait_line, out, release=True),
                                                          released=True, exercised=True)
            if args.exercise_orientation:
                validate_desktop_serial((out / 'serial.log').read_bytes(), with_input=True)
                orientation.run_probe(qmp, serial, wait_line, capture, display, args.rotation)
            if args.exercise_keyboard:
                home = validate_desktop_serial((out/'serial.log').read_bytes(), with_input=True)
                keyboard_result = {'passed':False, 'scope':'original Notes/Maliit touch input, real saved text and popup repaint; disposable snapshot'}
                try:
                    keyboard_result['timing'] = keyboard.run_probe(qmp, serial, wait_line, capture, display,
                        args.rotation, out, drain, performance)
                    keyboard_info['runtime'] = keyboard.validate_serial((out/'serial.log').read_bytes(), minimum_reports=12)
                    keyboard_result['service'] = keyboard_info
                    keyboard_result['notes'] = keyboard.validate_notes((out/'serial.log').read_bytes(), home,
                        {stage:raw_frame('keyboard-'+stage) for stage in keyboard.STAGES})
                    home_frames = guest_clock.compare_home_frames(raw_frame('settled'), raw_frame('keyboard-returned'), systemui_on and clock_on)
                    if not home_frames['content_equal']:
                        raise ValueError('Notes did not restore original Home content')
                    keyboard_result['home_frames'] = home_frames
                    keyboard_result['functional_checks_passed'] = True
                    keyboard_result['transitions'] = keyboard.motion.analyze(out)
                    (out/'keyboard-motion-result.json').write_text(json.dumps(keyboard_result['transitions'],indent=2)+'\n')
                    if not keyboard_result['transitions']['passed']:
                        raise ValueError('keyboard show/hide contains unexpected black frames')
                except Exception as error:
                    keyboard_result['error'] = str(error)
                    raise
                finally:
                    (out/'keyboard-result.json').write_text(json.dumps(keyboard_result,indent=2)+'\n')
            if args.exercise_calculator:
                validate_desktop_serial((out / 'serial.log').read_bytes(), with_input=True)
                if args.measure_performance:
                    measurements = performance.run_probe(qmp, serial, wait_line, capture, display,
                        args.rotation, out, process, drain, calculator)
                elif args.exercise_transitions:
                    transitions.run_probe(qmp, serial, wait_line, capture, display,
                        args.rotation, out, drain, performance)
                else:
                    calculator.run_probe(qmp, serial, wait_line, capture, display, args.rotation)
                if clock_on:
                    app_clock_phases = tuple(f'calculator-{stage}' for stage in calculator.STAGES)
                    clock_info['runtime'] = guest_clock.validate_serial(
                        (out / 'serial.log').read_bytes(), clock_snapshot['epoch'], clock_info['timezone_md5'],
                        additional_phases=app_clock_phases)
            if args.interactive:
                guest_result = validate_desktop_serial((out / 'serial.log').read_bytes(), with_input=True)
                host_startup = (systemui.validate_host((out / 'qemu-stderr.log').read_bytes(), live=True) if systemui_on
                                else validate_live_host((out / 'qemu-stderr.log').read_bytes()))
                first_raw, settled_raw = raw_frame('home'), raw_frame('settled')
                first, settled = desktop_frame(first_raw), desktop_frame(settled_raw)
                home_frames = guest_clock.compare_home_frames(first_raw, settled_raw, systemui_on and clock_on)
                if not home_frames['content_equal'] or any(item['exit'] for item in phases.values()):
                    raise ValueError('native window startup did not reach a stable original Home')
                clock_info['startup_frames'] = home_frames
                if animations_on:
                    animation_info['runtime'] = animations.validate_serial((out / 'serial.log').read_bytes(), animation_info['helper_md5'], require_root_guard=True)
                    if handoff_on:
                        animation_info['handoff_runtime'] = animations.validate_handoff((out / 'serial.log').read_bytes())
                if splash_on:
                    splash_info['runtime'] = splash.validate_serial((out / 'serial.log').read_bytes(), splash_info)
                if args.boot_animation:
                    boot_animation.reveal(out / 'boot', drain)
                    boot_info['desktop_revealed'] = True
                guard_info['released'] = startup.validate(startup.collect(serial, wait_line, out, release=True), released=True)
                ready = {'state': 'ready', 'scope': 'verified original Home startup with real guest input; no app or physical-input acceptance',
                    'command': command, 'qemu_pid': process.pid, 'controller_pid': os.getpid(),
                    'control_socket': control_path, 'rotation': args.rotation,
                    'surface_size': [480, 864] if args.rotation in (90, 270) else [864, 480],
                    'qemu_sha256': qemu_digest,
                    'runner_sha256': runner_digest,
                    'virtual_orientation': pose,
                    'system_ui': ui_service,
                    'clock': clock_info,
                    'input_method': keyboard_info,
                    'audio': audio_output.info if audio_output else {'enabled': False},
                    'compositor_animations': animation_info,
                    'splash': splash_info,
                    'startup_input': guard_info,
                    'boot_animation': boot_info,
                    'storage': {'persistent': profile_session is not None,
                                'profile': str(profile_session.path) if profile_session else None},
                    'guest': guest_result, 'native_frame': settled,
                    'host_startup': host_startup,
                    'startup_wall_seconds': round(time.monotonic() - started, 3)}
                ready.update(startup_waits=args.startup_waits, startup_observations=timings, phases=phases)
                (out / 'ready.json').write_text(json.dumps(ready, indent=2) + '\n')
                print(f'READY: original Home; input enabled. Evidence: {out}', flush=True)
                print('Left-button drag to scroll; close QEMU or Ctrl-C to stop. ' +
                      ('Saved files persist in the private profile.' if profile_session else 'Snapshot writes are discarded.'), flush=True)
                # Keep serial/QMP pipes drained while Cocoa owns user interaction.
                # This is the launcher lifecycle, not a background monitoring task.
                def interrupt(signum, frame):
                    raise KeyboardInterrupt
                previous_term = signal.signal(signal.SIGTERM, interrupt)
                def quit_guest():
                    nonlocal profile_synced
                    qmp.deadline = time.monotonic() + 40
                    if profile_session:
                        storage.sync_guest(serial, process, log, display)
                        profile_synced = True
                        qmp.call('stop')
                    qmp.call('quit')
                    process.wait(timeout=10)
                try:
                    if args.exit_on_ready:
                        quit_guest()
                    while process.poll() is None:
                        if audio_output:
                            audio_output.check()
                        if profile_session and storage.shutdown_requested(shutdown_request):
                            quit_guest()
                            break
                        readable, _, _ = select.select([serial, process.stdout], [], [], 1)
                        for source in readable:
                            chunk = os.read(source.fileno(), 65536)
                            if source is serial and chunk:
                                log.write(chunk); log.flush()
                except KeyboardInterrupt:
                    if process.poll() is None:
                        quit_guest()
                    process.wait(timeout=10)
                finally:
                    signal.signal(signal.SIGTERM, previous_term)
                if profile_session:
                    profile_session.finish(synced=profile_synced, exit_code=process.returncode)
                (out / 'interactive-exit.json').write_text(json.dumps({
                    'state': 'exited', 'qemu_exit': process.returncode,
                    'wall_seconds': round(time.monotonic() - started, 3),
                    'scope': 'interactive lifecycle only; inspect logs for application/GLES failures'}, indent=2) + '\n')
                if process.returncode != 0:
                    raise RuntimeError(f'interactive QEMU exited with {process.returncode}')
                if args.exit_on_ready:
                    final_host = host_validator((out / 'qemu-stderr.log').read_bytes())
                    (out / 'startup-result.json').write_text(json.dumps({
                        'passed': True, 'startup_waits': args.startup_waits,
                        'startup_wall_seconds': ready['startup_wall_seconds'],
                        'host': final_host, 'qemu_exit': process.returncode,
                        'scope': 'bounded interactive startup gates and clean exit; no physical input or display latency'},
                        indent=2) + '\n')
                    print(f'PASS: bounded original Home startup; evidence: {out}', flush=True)
                return
            # quit joins bridge workers; process presence above is not UI acceptance.
            qmp.call("quit")
            process.wait(timeout=5)
            host = (out / "qemu-stderr.log").read_bytes()
            if systemui_on:
                minimum = 3 + (6 if args.exercise_calculator else 0) + (len(orientation.STAGES) if args.exercise_orientation else 0)
                ui_service['runtime'] = systemui.validate_serial((out / 'serial.log').read_bytes(), minimum_reports=minimum)
            if animations_on:
                animation_info['runtime'] = animations.validate_serial((out / 'serial.log').read_bytes(), animation_info['helper_md5'],
                    minimum_reports=3 + (6 if args.exercise_calculator else 0), require_root_guard=True)
                if args.exercise_keyboard:
                    animation_info['input_handoff_runtime'] = animations.validate_input_handoff((out/'serial.log').read_bytes())
                if handoff_on:
                    animation_info['handoff_runtime'] = animations.validate_handoff((out / 'serial.log').read_bytes(),
                        minimum=4 if args.exercise_transitions else 1)
            failures = sorted(set(match.decode() for match in re.findall(rb"N00_GLES unsupported/invalid[^\n]+", host)))
            result = {"scope": "diagnostic only; no desktop or input acceptance", "phases": phases,
                "rotation": args.rotation,
                "surface_size": [480, 864] if args.rotation in (90, 270) else [864, 480],
                "unsupported_calls": failures, "qemu_exit": process.returncode, "command": command,
                "qemu_sha256": qemu_digest,
                "guest_sha256": hashlib.sha256(guest).hexdigest(),
                "inspector_sha256": hashlib.sha256(inspector).hexdigest(),
                "runner_sha256": runner_digest,
                "virtual_orientation": pose,
                "system_ui": ui_service,
                "clock": clock_info,
                "input_method": keyboard_info,
                "compositor_animations": animation_info,
                "splash": splash_info,
                "startup_input": guard_info,
                "startup_waits": args.startup_waits,
                "startup_observations": timings,
                "idle_profile": os.environ.get('HARMATTAN_UI_IDLE_PROFILE', 'unspecified'),
                "total_wall_seconds": round(time.monotonic() - started, 3)}
            (out / "diagnostic.json").write_text(json.dumps(result, indent=2) + "\n")
            if args.exercise_orientation:
                pose_result = {**result, 'scope': 'original Calendar follows virtual pose and returns Home; not full sensor or application acceptance',
                               'pose_checks_passed': False, 'frame_checks_passed': False,
                               'functional_checks_passed': False, 'host_graphics_clean': False, 'passed': False}
                try:
                    data = (out / 'serial.log').read_bytes()
                    home = validate_desktop_serial(data, with_input=True)
                    pose_result['calendar'] = orientation.validate_serial(data, home, pose['helper_md5'])
                    pose_result['pose_checks_passed'] = True
                except ValueError as error:
                    pose_result['pose_error'] = str(error)
                try:
                    initial = raw_frame('settled')
                    images = {tag: raw_frame(f'orientation-{tag}') for tag in orientation.STAGES}
                    # Preserve exact differences/hashes on failure as well as
                    # success. Evidence never changes the strict acceptance.
                    pose_result['frame_diagnostics'] = orientation.describe_frames(initial, images)
                    pose_result['frames'] = orientation.validate_frames(initial, images)
                    pose_result['frame_checks_passed'] = True
                except ValueError as error:
                    pose_result['frame_error'] = str(error)
                try:
                    pose_result['host'] = host_validator(host) if systemui_on else calculator.inspect_host(host, host_validator)
                    pose_result['host_graphics_clean'] = pose_result['host']['clean']
                except ValueError as error:
                    pose_result['host_error'] = str(error)
                pose_result['functional_checks_passed'] = (pose_result['pose_checks_passed'] and pose_result['frame_checks_passed']
                    and process.returncode == 0 and not any(item['exit'] for item in phases.values()))
                pose_result['passed'] = pose_result['functional_checks_passed'] and pose_result['host_graphics_clean']
                (out / 'orientation-result.json').write_text(json.dumps(pose_result, indent=2) + '\n')
                print(f'ORIENTATION: functional={pose_result["functional_checks_passed"]}; host_clean={pose_result["host_graphics_clean"]}', flush=True)
            if args.exercise_calculator:
                app_result = {**result, 'scope': 'original Calculator tap, 2+3=5, two edge returns and same-instance resume; no general app/performance acceptance',
                              'calculator_probe_sha256': calculator_digest,
                              'functional_checks_passed': False, 'host_graphics_clean': False, 'passed': False}
                if args.measure_performance:
                    app_result.update(scope='bounded CPU and first observed guest framebuffer with strict Calculator functional checks; no FPS/native-window latency acceptance',
                        performance_probe_sha256=performance_digest, startup_timings=timings, measurements=measurements)
                try:
                    serial_data = (out / 'serial.log').read_bytes()
                    home = validate_desktop_serial(serial_data, with_input=True)
                    app_result['guest'] = calculator.validate_serial(serial_data, home)
                    if splash_on:
                        splash_info['runtime'] = splash.validate_serial(serial_data, splash_info,
                            application_pid=app_result['guest']['pid'], minimum_reports=8)
                        splash_info['compositor_repairs'] = splash.validate_repairs(serial_data)
                    dynamic_statusbar = systemui_on and clock_on
                    app_result['frames'] = calculator.validate_frames(
                        raw_frame('settled'),
                        {stage: raw_frame(f'calculator-{stage}') for stage in calculator.STAGES},
                        allow_statusbar_change=dynamic_statusbar,
                        expect_statusbar_change=(dynamic_statusbar and clock_info['runtime']['minute_changed_after_home']))
                    app_result['functional_checks_passed'] = process.returncode == 0 and not any(item['exit'] for item in phases.values())
                    app_result['host'] = host_validator(host) if systemui_on else calculator.inspect_host(host, host_validator)
                    app_result['host_graphics_clean'] = app_result['host']['clean']
                    app_result['passed'] = app_result['functional_checks_passed'] and app_result['host_graphics_clean']
                except ValueError as error:
                    app_result['error'] = str(error)
                    raise
                finally:
                    (out / 'application-result.json').write_text(json.dumps(app_result, indent=2) + '\n')
                label = 'PASS' if app_result['passed'] else 'PARTIAL'
                print(f'{label}: Calculator functional={app_result["functional_checks_passed"]}; '
                      f'host_clean={app_result["host_graphics_clean"]}; evidence: {out}', flush=True)
                if not app_result['passed']:
                    raise SystemExit(2)
                if args.exercise_transitions:
                    motion = transitions.analyze(out, display, args.rotation)
                    motion.update(functional_checks_passed=app_result['functional_checks_passed'],
                                  host_graphics_clean=app_result['host_graphics_clean'],
                                  compositor_animations=animation_info,
                                  observer_sha256=hashlib.sha256(Path(transitions.__file__).read_bytes()).hexdigest())
                    motion['passed'] = (app_result['passed'] and motion['motion_frames_present']
                                        and motion['black_flash_eliminated_in_samples'])
                    (out / 'transition-result.json').write_text(json.dumps(motion, indent=2) + '\n')
                    print(f'MOTION: intermediate_frames={motion["motion_frames_present"]}; '
                          f'black_free={motion["black_flash_eliminated_in_samples"]}; evidence: {out}', flush=True)
                    if not motion['passed']:
                        raise SystemExit(2)
                    if args.exercise_keyboard:
                        keyboard_result.update(host_graphics_clean=app_result['host_graphics_clean'],
                                               transitions_passed=motion['passed'], passed=True)
                        (out/'keyboard-result.json').write_text(json.dumps(keyboard_result,indent=2)+'\n')
                        print('PASS: original keyboard, Notes, Calculator transitions and GPU', flush=True)
            if args.exercise_orientation and not pose_result['passed']:
                raise SystemExit(2)
            if args.verify_desktop or args.verify_input:
                serial_data = (out / "serial.log").read_bytes()
                guest_result = validate_desktop_serial(serial_data, with_input=args.verify_input)
                host_result = host_validator(host)
                first_raw, settled_raw = raw_frame('home'), raw_frame('settled')
                first, settled = desktop_frame(first_raw), desktop_frame(settled_raw)
                home_frames = guest_clock.compare_home_frames(first_raw, settled_raw, systemui_on and clock_on)
                if not home_frames['content_equal'] or process.returncode != 0 or any(item["exit"] for item in phases.values()):
                    raise ValueError("desktop did not remain stable or QEMU did not exit normally")
                clock_info['startup_frames'] = home_frames
                result.update(passed=True, scope="first original Home rendering only; raster theme path; no input/app/performance acceptance",
                              guest=guest_result, host=host_result, frame=settled)
                if args.verify_input:
                    result.update(scope='original Home single-touch scrolling and exact restoration; no app/portrait/performance acceptance',
                                  scroll=validate_scroll(serial_data, guest_result,
                                      raw_frame('settled'), raw_frame('scroll-1'), raw_frame('scroll-2')))
                    if args.rotation:
                        result['scope'] = 'original Home scrolling and exact restoration with rotated display/input; no app/performance acceptance'
                (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
                label = 'original Home single-touch scroll and exact restoration' if args.verify_input else 'original Home window and stable desktop rendering, no input'
                print(f"PASS: {label}; evidence: {out}", flush=True)
    finally:
        serial.close(); child.close()
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=5)
            process.stdin.close(); process.stdout.close()
        if profile_session:
            profile_session.close()
        if audio_output:
            audio_output.close()


if __name__ == "__main__":
    main()
