import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[3]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts/harmattan-qemu' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PACKAGES = load('armel-packages')
INSTALL = load('install-armel-packages')
MAINTENANCE = load('arm64-maintenance')
CONTROL = b'Package: test-note\nVersion: 1.2-3\nArchitecture: armel\nDescription: Note\n continuation\n'


def archive(members):
    data = b'!<arch>\n'
    for name, value in members:
        data += f'{name + "/":<16}{0:<12}{0:<6}{0:<6}{100644:<8}{len(value):<10}`\n'.encode()
        data += value + (b'\n' if len(value) % 2 else b'')
    return data


def package(control=CONTROL, extra=(), signature=False):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w:gz') as tar:
        for name, data in [('control', control), *extra]:
            member = tarfile.TarInfo(name)
            member.size = len(data)
            tar.addfile(member, io.BytesIO(data))
    entries = [('debian-binary', b'2.0\n'), ('control.tar.gz', stream.getvalue()), ('data.tar.gz', b'not extracted by inspector')]
    if signature:
        entries.append(('_x509sig', b'original opaque signature'))
    return archive(entries)


class PackageTests(unittest.TestCase):
    def test_original_identity_scripts_and_signature_are_reported(self):
        script = b'#!/bin/sh\nexit 0\n'
        result = PACKAGES.inspect_bytes(package(extra=[('postinst', script)], signature=True))
        self.assertEqual((result['package'], result['version'], result['architecture']), ('test-note', '1.2-3', 'armel'))
        self.assertEqual(result['maintainer_scripts'], {'postinst': script.decode()})
        self.assertTrue(result['historical_signature_present'])
        self.assertFalse(result['signature_verified'])

    def test_wrong_abi_and_command_characters_rejected(self):
        for value in (CONTROL.replace(b'armel', b'arm64'), CONTROL.replace(b'armel', b'amd64'),
                      CONTROL.replace(b'test-note', b'note;id'), CONTROL.replace(b'1.2-3', b'$(id)'),
                      CONTROL + b'Package: duplicate\n', CONTROL.replace(b'Architecture: armel\n', b'')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                PACKAGES.inspect_bytes(package(control=value))

    def test_control_paths_duplicates_and_limits_rejected(self):
        for extra in ([('../outside', b'x')], [('/control', b'x')], [('control', CONTROL)],
                      [('postinst', b'x' * (1024 ** 2 + 1))], [(str(i), b'') for i in range(65)]):
            with self.subTest(names=[x[0] for x in extra]), self.assertRaises(ValueError):
                PACKAGES.inspect_bytes(package(extra=extra))

    def test_malformed_archive_does_not_silently_truncate(self):
        good = package()
        for bad in (b'', good[:-1], good[:70], good + good[8:],
                    archive([('debian-binary', b'1.0\n')]),
                    good + archive([('unknown', b'x')])[8:]):
            with self.subTest(length=len(bad)), self.assertRaises(ValueError):
                PACKAGES.inspect_bytes(bad)

    def test_duplicate_batch_rejected_before_guest_open(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'note.deb'
            path.write_bytes(package())
            records, payloads = INSTALL.prepare([path])
            self.assertEqual(payloads, [path.read_bytes()])
            self.assertEqual(records[0]['filename'], path.name)
            for paths in ([], [path, path], [path] * 25):
                with self.assertRaises(ValueError):
                    INSTALL.prepare(paths)

    def test_install_requires_exact_configured_version_and_order(self):
        records = [PACKAGES.inspect_bytes(package())]
        good = b'N00_PACKAGE test-note 1.2-3 install ok installed\n'
        INSTALL.validate_install(good, records)
        for bad in (b'', good + good, good.replace(b'1.2-3', b'1.2-2'),
                    good.replace(b'installed', b'unpacked'), good.replace(b'ok', b'reinstreq')):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                INSTALL.validate_install(bad, records)

    def test_failure_exit_cannot_be_hidden_by_done_marker(self):
        good = b'N00_INSTALL_EXIT_0\r\nN00_INSTALL_DONE\r\n'
        MAINTENANCE.completed(good, 'N00_INSTALL')
        for bad in (b'', good + good, good.replace(b'EXIT_0', b'EXIT_1'),
                    good + b'N00_INSTALL_EXIT_2\n', good.replace(b'N00_INSTALL_DONE', b'/ # N00_INSTALL_DONE')):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                MAINTENANCE.completed(bad, 'N00_INSTALL')

    def test_early_qemu_exit_never_marks_profile_clean(self):
        profile = Mock()
        session = MAINTENANCE.Session([], '.', profile)
        session.process = Mock()
        session.process.poll.return_value = 0
        session.ready = True
        with patch.object(session, 'close') as close, self.assertRaisesRegex(RuntimeError, 'before.*flush'):
            session.__exit__(None, None, None)
        profile.finish.assert_not_called()
        close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
