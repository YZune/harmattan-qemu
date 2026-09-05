import importlib.util
from pathlib import Path
import subprocess
import unittest

SPEC = importlib.util.spec_from_file_location("shell_smoke", Path(__file__).resolve().parents[1] / "diagnose-arm64-shell.py")
SMOKE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SMOKE)


def observation(home_pid=155):
    lines = []
    for name, pid, uid in (("Xorg", 98, 0), ("mthemedaemon", 117, 29999),
                           ("mcompositor", 137, 29999), ("meegotouchhome", home_pid, 29999)):
        lines.append(f"N00_SHELL_PROCESS {name} {pid}\nName:\t{name}\nState:\tS (sleeping)\n"
                     f"Tgid:\t{pid}\nPid:\t{pid}\nPPid:\t1\nTracerPid:\t0\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n")
    lines.extend(("N00_X11_ROOT id=00000044 size=864x480 depth=24\n",
                  "N00_X11_WM check=00400017 self=00400017\n",
                  "N00_X11_COMPOSITOR owner=00400017\n",
                  "N00_X11_CLIENTS 00800002\n",
                  f"N00_X11_WINDOW id=00800002 map=2 geometry=864x480+0+0 pid={home_pid} class=" +
                  b"meegotouchhome\0Meegotouchhome\0".hex() + "\n",
                  "N00_X11_INSPECT_OK\n"))
    return "".join(lines).encode()


def serial_log(restarted=False):
    parts = []
    for phase in SMOKE.PHASES:
        parts.append(f"N00_SHELL_BEGIN_{phase}\n".encode())
        if phase == "bootstrap":
            parts.append(b"N00_SHELL_INPUT_NOT_IMPLEMENTED\n")
            parts.extend(f"{digest}  {name}\n".encode() for name, digest in SMOKE.LIBRARIES.items())
        if phase in ("home", "settled"):
            parts.append(observation(156 if restarted and phase == "settled" else 155))
        parts.append(f"\nN00_SHELL_PHASE_{phase}_0\n".encode())
    return b"".join(parts)


def host_log():
    return (b"N00_GLES connect client=0 abi=1\nN00_GLES connect client=1 abi=2\n"
            b"N00_GLES current client=1 es=2 renderer=Apple Test GPU\n"
            b"N00_GLES connect client=2 abi=2\nN00_GLES current client=2 es=2 renderer=Apple Test GPU\n"
            b"N00_GLES disconnect client=1\nN00_GLES disconnect client=2\nN00_GLES disconnect client=0\n"
            b"N00_GLES render compiles=9 links=6 uploads=139 draws=4 rejects=0\n"
            b"N00_GLES summary calls=1374 swaps=5 faults=0 workers=joined\n")


class ShellRenderingGateTests(unittest.TestCase):
    def test_live_startup_cannot_hide_host_warning(self):
        startup = b'\n'.join(host_log().split(b'\n')[:5]) + b'\n'
        self.assertTrue(SMOKE.validate_live_host(startup)['shutdown_summary_pending'])
        for value in (startup + b'warning: Blocked re-entrant IO\n', startup.replace(b'Apple', b'Software'), b''):
            with self.assertRaises(ValueError):
                SMOKE.validate_live_host(value)

    def input_log(self):
        data = serial_log().replace(b'N00_SHELL_INPUT_NOT_IMPLEMENTED', b'N00_SHELL_INPUT_REAL /dev/input/event1')
        data += (b'mtev: caps: mtdata touch_major tracking_id position_x position_y\n'
                 b'mtev: position_x: 0 863\nmtev: position_y: 0 479\n')
        for step in (1, 2):
            data += f'N00_INPUT_SCROLL_{step}\n'.encode() + observation() + f'N00_INPUT_SCROLL_DONE_{step}\n'.encode()
        return data

    def scroll_frames(self):
        # Distinct synthetic pixel sets exercise the gate, not visual acceptance.
        palette = b''.join(bytes((i >> 8, i & 255, 0)) for i in range(8192))
        rgb = (palette * 51)[:414720 * 3]
        header = b'P6\n864 480\n255\n'
        return header + rgb, header + bytes(value ^ 255 for value in rgb)

    def test_real_input_profile_cannot_accept_missing_driver(self):
        SMOKE.validate_desktop_serial(self.input_log(), with_input=True)
        for data in (serial_log(), self.input_log().replace(b'mtev: position_x: 0 863', b''),
                     self.input_log() + b'(EE) mtev: cannot open device\n',
                     self.input_log() + b'(EE) Couldn\'t init device "Atmel mXT Touchscreen"\n'):
            with self.assertRaises(ValueError):
                SMOKE.validate_desktop_serial(data, with_input=True)

    def test_scroll_changes_and_restores_pixels(self):
        before, after = self.scroll_frames()
        home = SMOKE.validate_desktop_serial(self.input_log(), with_input=True)
        result = SMOKE.validate_scroll(self.input_log(), home, before, after, before)
        self.assertEqual(result['changed_pixels'], 414720)
        for moved, back in ((before, before), (after, after), (after, before[:-1])):
            with self.assertRaises(ValueError):
                SMOKE.validate_scroll(self.input_log(), home, before, moved, back)

    def test_scrolled_home_remains_mapped_and_managed(self):
        before, after = self.scroll_frames()
        home = SMOKE.validate_desktop_serial(self.input_log(), with_input=True)
        for old, new in ((b'pid=155 class=', b'pid=999 class='), (b'map=2', b'map=0'),
                         (b'N00_X11_CLIENTS 00800002', b'N00_X11_CLIENTS 00800003'),
                         (b'N00_INPUT_SCROLL_DONE_2', b'echo N00_INPUT_SCROLL_DONE_2')):
            with self.assertRaises(ValueError):
                SMOKE.validate_scroll(self.input_log().replace(old, new), home, before, after, before)

    def test_real_managed_home_and_stable_process_identities(self):
        result = SMOKE.validate_desktop_serial(serial_log())
        self.assertEqual(result["home_window"], "00800002")
        self.assertEqual(result["pids"]["meegotouchhome"], 155)

    def test_phase_completion_once_and_no_failed_phase(self):
        for phase in SMOKE.PHASES:
            end = f"N00_SHELL_PHASE_{phase}_0".encode()
            for data in (serial_log().replace(end, b"echo " + end),
                         serial_log() + end + b"\n", serial_log().replace(end, end[:-1] + b"1")):
                with self.assertRaises(ValueError):
                    SMOKE.validate_desktop_serial(data)

    def test_stopped_or_wrong_user_is_not_live_shell(self):
        for old, new in ((b"State:\tS", b"State:\tT"), (b"TracerPid:\t0", b"TracerPid:\t1"),
                         (b"Uid:\t29999", b"Uid:\t0"), (b"N00_SHELL_PROCESS mcompositor 137", b"N00_SHELL_PROCESS mcompositor absent")):
            with self.assertRaises(ValueError):
                SMOKE.validate_desktop_serial(serial_log().replace(old, new))

    def test_original_executable_and_library_digests_required(self):
        for digest in SMOKE.LIBRARIES.values():
            with self.assertRaises(ValueError):
                SMOKE.validate_desktop_serial(serial_log().replace(digest.encode(), b"0" * 32))

    def test_window_identity_mapping_geometry_and_managed_list(self):
        for old, new in ((b"map=2", b"map=0"), (b"geometry=864x480", b"geometry=854x480"),
                         (b"pid=155 class=", b"pid=156 class="),
                         (b"N00_X11_CLIENTS 00800002", b"N00_X11_CLIENTS 00800003"),
                         (b"size=864x480", b"size=480x864")):
            with self.assertRaises(ValueError):
                SMOKE.validate_desktop_serial(serial_log().replace(old, new))

    def test_manager_self_check_and_selection_owner_must_agree(self):
        for old, new in ((b"self=00400017", b"self=00400018"),
                         (b"owner=00400017", b"owner=00000000")):
            with self.assertRaises(ValueError):
                SMOKE.validate_desktop_serial(serial_log().replace(old, new))

    def test_restart_between_observations_is_rejected(self):
        with self.assertRaises(ValueError):
            SMOKE.validate_desktop_serial(serial_log(restarted=True))

    def test_known_missing_input_explicit_unknown_errors_rejected(self):
        data = serial_log() + b"\n".join(b"(EE) " + error for error in SMOKE.xorg.INPUT_ERRORS) + b"\n"
        self.assertEqual(len(SMOKE.validate_desktop_serial(data)["known_input_errors"]), 7)
        for data in (serial_log().replace(b"N00_SHELL_INPUT_NOT_IMPLEMENTED", b"INPUT_OK"),
                     serial_log() + b"(EE) Render failed\n", serial_log() + b"Segmentation fault\n",
                     serial_log() + b"MTexturePixmapItem::update(): std::bad_alloc e\n"):
            with self.assertRaises(ValueError):
                SMOKE.validate_desktop_serial(data)

    def test_host_requires_real_rendering_no_faults_and_all_workers(self):
        self.assertEqual(SMOKE.validate_desktop_host(host_log())["draws"], 4)
        for old, new in ((b"Apple Test GPU", b"Software"), (b"draws=4", b"draws=0"),
                         (b"swaps=5", b"swaps=0"), (b"rejects=0", b"rejects=1"),
                         (b"faults=0", b"faults=1"), (b"workers=joined", b"workers=running")):
            with self.assertRaises(ValueError):
                SMOKE.validate_desktop_host(host_log().replace(old, new))
        with self.assertRaises(ValueError):
            SMOKE.validate_desktop_host(host_log() + b"unexpected output")

    def test_frame_heuristic_excludes_black_or_simple_probes(self):
        header = b"P6\n864 480\n255\n"
        for color in (b"\0\0\0", b"\xff\0\xff"):
            with self.assertRaises(ValueError):
                SMOKE.desktop_frame(header + color * 414720)
        # Synthetic validator fixture, not screenshot evidence.
        palette = b"".join(bytes((i >> 8, i & 255, 0)) for i in range(8192))
        data = header + (palette * 51)[:414720 * 3]
        self.assertEqual(SMOKE.desktop_frame(data)["colors"], 8192)
        for bad in (data[:-1], data + b"\0", data.replace(b"864 480", b"480 864", 1)):
            with self.assertRaises(ValueError):
                SMOKE.desktop_frame(bad)


class NativeDisplaySelectionTests(unittest.TestCase):
    def selected_display(self, mode):
        launcher = (Path(__file__).resolve().parents[1] / 'run-arm64-ui.sh').read_text()
        # Execute the launcher's actual display-selection block without touching
        # images or starting QEMU. This is option routing, not pointer acceptance.
        block = launcher[launcher.index('\ndisplay=') + 1:launcher.index('\nbuild_options=')]
        result = subprocess.run(
            ['/bin/sh', '-eu', '-c', 'mode=$1; rotation=270\n' + block + '\nprintf "%s" "$display"',
             'display-selection', mode], capture_output=True, text=True, timeout=3, check=True)
        return result.stdout

    def test_interactive_host_cursor_stays_visible(self):
        self.assertEqual(self.selected_display('interactive'), 'cocoa,zoom-to-fit=on,show-cursor=on')

    def test_diagnostic_display_options_are_unchanged(self):
        for mode in ('--smoke', '--calculator-diagnostic', '--performance-diagnostic'):
            with self.subTest(mode=mode):
                self.assertEqual(self.selected_display(mode), 'cocoa,zoom-to-fit=on')
        for mode in ('--serial-smoke', '--headless-smoke', '--display-smoke', '--input-smoke',
                     '--landscape-smoke', '--calculator-headless-diagnostic', '--performance-headless-diagnostic'):
            with self.subTest(mode=mode):
                self.assertEqual(self.selected_display(mode), 'none')


if __name__ == "__main__":
    unittest.main()
