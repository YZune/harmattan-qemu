import importlib.util
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location('pose', ROOT / 'scripts/harmattan-qemu/arm64-orientation.py')
POSE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POSE)
HELPER_MD5 = 'a' * 32
HOME = {'home_window': '00800002', 'wm_window': '00400017', 'pids': {'meegotouchhome': 199}}


def provider(edge='left'):
    return (f'N00_ORIENTATION_EXPECT edge={edge} provider=org.harmattan.QemuOrientation\n'
            f'N00_ORIENTATION_TOP_EDGE_BEGIN\nmethod return\n   array [\n      variant string "{edge}"\n   ]\n   uint64 12\nN00_ORIENTATION_TOP_EDGE_END\n'
            'N00_ORIENTATION_IS_FLAT_BEGIN\nmethod return\n   array [\n      variant boolean false\n   ]\n   uint64 12\nN00_ORIENTATION_IS_FLAT_END\n'
            'N00_ORIENTATION_PROCESS 141\nName:\tprovider\nState:\tS (sleeping)\nTgid:\t141\nPid:\t141\nPPid:\t1\nTracerPid:\t0\nUid:\t29999\t29999\t29999\t29999\n'
            f'{HELPER_MD5}  /tmp/n00-qemu-orientation/provider\n{HELPER_MD5}  /proc/141/exe\n' +
            ''.join(f'{digest}  {path}\n' for path, digest in POSE.REGISTRY.items()) +
            f'N00_ORIENTATION_READY {edge}\n').encode()


def observation(tag):
    edge = 'top' if tag.endswith('landscape') else 'left'
    active = '00800002' if tag == 'home' else '00a00002'
    clients = '00a00002,00800002' if tag == 'home' else '00800002,00a00002'
    return (f'\nN00_POSE_BEGIN_{tag}\n'.encode() + provider(edge) +
            (f'{POSE.CALENDAR_MD5}  /usr/bin/organiser\nN00_CALENDAR_PROCESS 280\n'
             'Name:\torganiser\nState:\tS (sleeping)\nTgid:\t280\nPid:\t280\nPPid:\t1\nTracerPid:\t0\nUid:\t29999\t29999\t29999\t29999\n'
             f'{POSE.CALENDAR_MD5}  /proc/280/exe\n'
             'CONTEXT_PROVIDERS=/tmp/n00-qemu-orientation/providers\n'
             'N00_X11_WM check=00400017 self=00400017\nN00_X11_COMPOSITOR owner=00400017\n'
             f'N00_X11_CLIENTS {clients}\nN00_X11_ACTIVE id={active}\n'
             'N00_X11_WINDOW id=00800002 map=2 geometry=864x480+0+0 pid=199 class=' + b'meegotouchhome\0Meegotouchhome\0'.hex() + '\n'
             'N00_X11_WINDOW id=00a00002 map=2 geometry=864x480+0+0 pid=280 class=' + b'organiser\0Organiser\0'.hex() + '\n'
             f'N00_X11_ORIENTATION id=00a00002 angle={0 if edge == "top" else 270}\n'
             f'N00_X11_INSPECT_OK\nN00_POSE_EXIT_{tag}_0\nN00_POSE_DONE_{tag}\n').encode())


def frames():
    # Deliberately synthetic: validator mechanics, not visual app acceptance.
    header = b'P6\n864 480\n255\n'
    image = lambda color: header + bytes(color) * (864 * 480)
    initial, portrait, landscape, calendar, rotated = [image((n, n, n)) for n in (0, 10, 20, 30, 40)]
    return initial, dict(portrait=portrait, landscape=landscape, restored=portrait, calendar=calendar,
                        calendarlandscape=rotated, calendarrestored=calendar, home=initial)


class OrientationTests(unittest.TestCase):
    def test_default_is_interactive_only(self):
        for rotation, edge in POSE.EDGES.items():
            self.assertEqual(POSE.select_edge(None, True, rotation), edge)
            self.assertIsNone(POSE.select_edge(None, False, rotation))
            self.assertIsNone(POSE.select_edge('disabled', True, rotation))
            self.assertEqual(POSE.select_edge('display', False, rotation), edge)
            self.assertEqual(POSE.select_edge('left', False, rotation), 'left')

    def test_bad_options_fail(self):
        for mode, rotation in (('left; reboot', 270), ('LEFT', 270), ('display', 45)):
            with self.assertRaises(ValueError):
                POSE.select_edge(mode, True, rotation)

    def test_provider_reads_actual_values_and_original_registry(self):
        value = POSE.validate_provider(provider(), 'left', HELPER_MD5)
        self.assertEqual((value['edge'], value['flat'], value['uid']), ('left', False, 29999))
        for old, new in ((b'string "left"', b'string "top"'), (b'boolean false', b'boolean true'),
                         (b'Uid:\t29999', b'Uid:\t0'), (b'State:\tS', b'State:\tT'),
                         (b'TracerPid:\t0', b'TracerPid:\t1'), (b'Pid:\t141', b'Pid:\t142'),
                         (HELPER_MD5.encode(), b'b' * 32), (b'uint64 12', b''),
                         (b'N00_ORIENTATION_READY left', b'N00_ORIENTATION_READY top'),
                         (next(iter(POSE.REGISTRY.values())).encode(), b'0' * 32)):
            with self.subTest(old=old), self.assertRaises(ValueError):
                POSE.validate_provider(provider().replace(old, new), 'left', HELPER_MD5)

    def test_markers_require_success_once(self):
        good = observation('portrait')
        POSE.block(good, 'portrait')
        for bad in (good + good, good.replace(b'_portrait_0', b'_portrait_1'),
                    good.replace(b'\nN00_POSE_DONE_portrait', b'\necho N00_POSE_DONE_portrait'), b''):
            with self.assertRaises(ValueError):
                POSE.block(bad, 'portrait')

    def test_calendar_rotation_and_exact_returns(self):
        data = b''.join(map(observation, POSE.STAGES))
        initial, images = frames()
        result = POSE.validate_probe(data, HOME, HELPER_MD5, initial, images)
        self.assertTrue(result['same_instance'])
        self.assertTrue(result['portrait_restored_exactly'])
        self.assertEqual(result['observations']['landscape']['angle'], 0)

    def test_calendar_wrong_identity_or_angle_cannot_pass(self):
        data = b''.join(map(observation, POSE.STAGES))
        initial, images = frames()
        for old, new in ((b'angle=270', b'angle=0'), (b'angle=0', b'angle=absent'),
                         (b'N00_CALENDAR_PROCESS 280', b'N00_CALENDAR_PROCESS 281'),
                         (POSE.CALENDAR_MD5.encode(), b'b' * 32),
                         (b'N00_X11_ACTIVE id=00a00002', b'N00_X11_ACTIVE id=00800002'),
                         (b'pid=199 class=', b'pid=200 class='),
                         (b'CONTEXT_PROVIDERS=/tmp/n00-qemu-orientation/providers', b''),
                         (b'N00_X11_COMPOSITOR owner=00400017', b'N00_X11_COMPOSITOR owner=00400018')):
            with self.subTest(old=old), self.assertRaises(ValueError):
                POSE.validate_probe(data.replace(old, new), HOME, HELPER_MD5, initial, images)

    def test_reordering_missing_or_restarted_instance_fails(self):
        data = b''.join(map(observation, POSE.STAGES))
        initial, images = frames()
        for altered in (data + observation('home'), data.replace(observation('home'), b''),
                        b''.join(map(observation, reversed(POSE.STAGES))),
                        data.replace(observation('restored'), observation('restored').replace(b'280', b'281')),
                        data.replace(observation('restored'), observation('restored').replace(b'141', b'142'))):
            with self.assertRaises(ValueError):
                POSE.validate_probe(altered, HOME, HELPER_MD5, initial, images)

    def test_unchanged_onboarding_or_bad_restoration_fails(self):
        data = b''.join(map(observation, POSE.STAGES))
        initial, images = frames()
        for tag, replacement in (('home', images['portrait']), ('restored', images['landscape']),
                                 ('landscape', images['portrait']), ('calendarrestored', images['portrait']),
                                 ('calendar', images['portrait']), ('calendar', b'')):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                POSE.validate_probe(data, HOME, HELPER_MD5, initial, {**images, tag: replacement})

    def test_invalid_guest_operation_exits_before_runtime_access(self):
        script = ROOT / 'scripts/harmattan-qemu/orientation-guest.sh'
        for args in (['start', 'left; reboot'], ['unknown', 'left'], ['start'], []):
            result = subprocess.run(['sh', str(script), *args], capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 2)

    def test_failed_frame_report_keeps_full_native_difference(self):
        initial, images = frames()
        changed = bytearray(images['calendarrestored'])
        # Distinct RGB channels at opposite native corners; not a display ROI.
        header = len(b'P6\n864 480\n255\n')
        changed[header + 1] ^= 1
        changed[-1] ^= 1
        images['calendarrestored'] = bytes(changed)
        report = POSE.describe_frames(initial, images)
        self.assertEqual(report['native_size'], [864, 480])
        self.assertEqual(report['round_trips']['calendar'],
                         {'exact': False, 'changed_pixels': 2, 'bbox': [0, 0, 864, 480]})
        self.assertEqual(report['round_trips']['home'], {'exact': True, 'changed_pixels': 0, 'bbox': None})
        self.assertNotEqual(report['native_rgb_sha256']['calendar'], report['native_rgb_sha256']['calendarrestored'])
        self.assertEqual(set(report['native_rgb_sha256']), set(POSE.STAGES))
        with self.assertRaisesRegex(ValueError, 'calendar pixels were not restored'):
            POSE.validate_frames(initial, images)

    def test_difference_counts_pixels_not_channels_and_has_exclusive_bbox(self):
        initial, images = frames()
        changed = bytearray(images['home'])
        offset = len(b'P6\n864 480\n255\n') + (23 * 864 + 41) * 3
        changed[offset:offset + 3] = b'\x01\x02\x03'
        images['home'] = bytes(changed)
        report = POSE.describe_frames(initial, images)
        self.assertEqual(report['round_trips']['home'],
                         {'exact': False, 'changed_pixels': 1, 'bbox': [41, 23, 42, 24]})
        with self.assertRaisesRegex(ValueError, 'Home pixels exactly'):
            POSE.validate_frames(initial, images)

    def test_frame_report_rejects_missing_extra_or_invalid_frames(self):
        initial, images = frames()
        for bad in ({k: v for k, v in images.items() if k != 'home'},
                    {**images, 'extra': initial}, {**images, 'home': initial[:-1]},
                    {**images, 'portrait': b'P6\n480 864\n255\n' + initial[16:]}):
            with self.subTest(stages=list(bad)), self.assertRaises(ValueError):
                POSE.describe_frames(initial, bad)


if __name__ == '__main__':
    unittest.main()
