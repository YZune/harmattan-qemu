import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location('systemui', ROOT / 'scripts/harmattan-qemu/arm64-systemui.py')
UI = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(UI)


def report(pid=148, pixmap=6291478):
    return (f'\nN00_SYSTEMUI_REPORT_BEGIN\nN00_SYSTEMUI_PROCESS {pid}\n'
            f'Name:\tsysuid\nState:\tS (sleeping)\nTgid:\t{pid}\nPid:\t{pid}\nPPid:\t1\nTracerPid:\t0\nUid:\t29999\t29999\t29999\t29999\n'
            f'{UI.SYSUID_MD5}  /usr/bin/sysuid\n{UI.SYSUID_MD5}  /proc/{pid}/exe\n'
            f'N00_SYSTEMUI_OWNER_BEGIN\nmethod return\n   uint32 {pid}\nN00_SYSTEMUI_OWNER_END\n'
            f'N00_SYSTEMUI_PIXMAP_BEGIN\nmethod return\n   uint32 {pixmap}\nN00_SYSTEMUI_PIXMAP_END\n'
            'N00_SYSTEMUI_REPORT_END\n').encode()


def serial():
    geometry = b'N00_X11_STATUSBAR window=00600018 pixmap=00600016 size=864x72 depth=24\n'
    return report() + report() + geometry + report() + geometry


def host(live=False):
    lines = [b'N00_GLES connect client=0 abi=1']
    for client in (1, 2, 3):
        lines += [f'N00_GLES connect client={client} abi=2'.encode(),
                  f'N00_GLES current client={client} es=2 renderer=Apple Test GPU'.encode()]
    lines += [b'N00_GLES terminate client=1 released=1 backend=retained',
              b'N00_GLES terminate client=1 rejected=bad-display']
    if not live:
        lines += [f'N00_GLES disconnect client={c}'.encode() for c in (1, 2, 3, 0)]
        lines += [b'N00_GLES render compiles=9 links=6 uploads=108 draws=454 rejects=0',
                  b'N00_GLES summary calls=12201 swaps=131 faults=0 workers=joined']
    return b'\n'.join(lines) + b'\n'


class SystemUITests(unittest.TestCase):
    def test_only_interactive_default_changes(self):
        self.assertTrue(UI.enabled(None, True))
        self.assertFalse(UI.enabled(None, False))
        self.assertTrue(UI.enabled('on', False))
        self.assertFalse(UI.enabled('off', True))
        with self.assertRaises(ValueError): UI.enabled('invalid', True)

    def test_actual_original_owner_and_shared_drawable(self):
        value = UI.validate_serial(serial())
        self.assertEqual(value['size'], [864, 72])
        self.assertEqual(value['pid'], 148)
        self.assertEqual(value['reports'], 3)
        self.assertEqual(UI.validate_serial(report(), 1)['size'], [None, None])

    def test_missing_owner_fake_binary_invalid_uid_or_empty_pixmap_fails(self):
        for old, new in ((b'uint32 148', b'uint32 149'), (b'uint32 6291478', b'uint32 0'),
                         (b'Uid:\t29999', b'Uid:\t0'), (b'State:\tS', b'State:\tT'), (b'State:\tS', b'State:\tD'),
                         (b'TracerPid:\t0', b'TracerPid:\t1'), (UI.SYSUID_MD5.encode(), b'a' * 32),
                         (b'pixmap=00600016', b'pixmap=00600017'), (b'size=864x72', b'size=864x0'),
                         (b'depth=24', b'depth=1'), (b'N00_SYSTEMUI_OWNER_END', b'echo N00_SYSTEMUI_OWNER_END')):
            with self.subTest(old=old), self.assertRaises(ValueError):
                UI.validate_serial(serial().replace(old, new))

    def test_missing_reports_or_restarted_service_cannot_pass(self):
        for data in (b'', report(), serial().replace(report(), b'', 1), serial() + report(149),
                     serial() + report(pixmap=6291479), serial() + b'N00_SYSTEMUI_REPORT_BEGIN\n',
                     serial() + b'N00_X11_STATUSBAR absent\n'):
            with self.assertRaises(ValueError): UI.validate_serial(data)

    def test_clean_gpu_keeps_known_guest_api_defect_explicit(self):
        value = UI.validate_host(host())
        self.assertTrue(value['clean'])
        self.assertEqual(value['gpu_contexts'], 3)
        self.assertEqual(value['faults'], 0)
        self.assertEqual(len(value['known_guest_api_defects']), 1)
        self.assertTrue(UI.validate_host(host(True), live=True)['shutdown_summary_pending'])

    def test_every_gpu_warning_and_unknown_line_still_fails(self):
        warning = (b'UNSUPPORTED (log once): POSSIBLE ISSUE: unit 0 GLD_TEXTURE_INDEX_2D is '
                   b'unloadable and bound to sampler type (Float) - using zero texture because texture unloadable\n')
        for data in (host() + warning, warning + host(), host() + b'warning: Blocked re-entrant IO\n',
                     host().replace(b'faults=0', b'faults=1'), host().replace(b'rejects=0', b'rejects=1'),
                     host().replace(b'workers=joined', b'workers=pending'), host().replace(b'Apple', b'Software'),
                     host().replace(b'rejected=bad-display', b'rejected=current-context')):
            with self.assertRaises(ValueError): UI.validate_host(data)

    def test_client_and_terminate_lifetimes_are_not_silenced(self):
        release = b'N00_GLES terminate client=1 released=1 backend=retained\n'
        reject = b'N00_GLES terminate client=1 rejected=bad-display\n'
        for data in (host().replace(release, b''), host().replace(reject, b''),
                     host().replace(release, release + reject + release),
                     host().replace(b'connect client=3 abi=2', b'connect client=2 abi=2'),
                     host().replace(b'disconnect client=2', b'disconnect client=3'),
                     host().replace(b'N00_GLES disconnect client=0\n', b'N00_GLES disconnect client=0\n' * 2),
                     host().replace(b'N00_GLES disconnect client=0\n', b'')):
            with self.assertRaises(ValueError): UI.validate_host(data)
        with self.assertRaises(ValueError): UI.validate_host(host(), live=True)
        with self.assertRaises(ValueError): UI.validate_host(host(True))


if __name__ == '__main__': unittest.main()
