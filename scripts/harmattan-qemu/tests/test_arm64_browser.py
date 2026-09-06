import hashlib
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('browser', SCRIPTS / 'arm64-browser.py')
BROWSER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BROWSER)


class BrowserTests(unittest.TestCase):
    def test_only_verified_browser_changes_compositing_and_preserves_requested_attribute(self):
        with tempfile.TemporaryDirectory() as temporary:
            binary = str(Path(temporary) / 'probe')
            subprocess.run(['cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                str(SCRIPTS / 'browser-guest.c'), str(SCRIPTS / 'tests/browser-host.c'), '-o', binary], check=True)
            for mode in range(13):
                with self.subTest(mode=mode):
                    result = subprocess.run([binary, str(mode)], capture_output=True, timeout=5)
                    self.assertEqual(result.returncode, 123 if mode >= 6 else 0, result.stderr)
                    self.assertEqual(result.stdout, b'N00_BROWSER_SOFTWARE_COMPOSITING verified\n' if mode == 0 else b'')

    def test_entry_requires_pinned_bytes_and_preserves_arguments(self):
        data = b'Exec=/usr/bin/invoker --type=m /usr/bin/grob -prestart\n'
        digest = hashlib.md5(data).hexdigest()
        self.assertEqual(BROWSER.adapt_entry(data, digest),
            b'Exec=/usr/bin/invoker --type=m /tmp/n00-ui-helpers/browser-launch-guest.sh -prestart\n')
        for bad in (data + b'changed', b'', data + data):
            with self.assertRaises(ValueError):
                BROWSER.adapt_entry(bad, digest)

    def test_serial_entry_export_preserves_framing_with_shell_prompts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            entries = {}
            for name, (target, _) in BROWSER.ENTRIES.items():
                data = b'Exec=/usr/bin/invoker --type=m /usr/bin/grob -prestart\n'
                (root / name).write_bytes(data)
                entries[name] = target, hashlib.md5(data).hexdigest()
            def send(command):
                # Execute only the read-only export with temporary fixture
                # paths. Never run a guest mount/setup script on the host.
                for name, (target, _) in entries.items():
                    command = command.replace(target.encode(), str(root / name).encode())
                result = subprocess.run(['sh'], input=command, capture_output=True, check=True)
                (root / 'serial.log').write_bytes(b'/ # ' + result.stdout + b'/ # ')
            payloads = {}
            info = {}
            with patch.object(BROWSER, 'ENTRIES', entries):
                BROWSER.install(SimpleNamespace(sendall=send), lambda marker: None,
                    lambda data, target, tag: payloads.update({target: data}), root, info)
            self.assertEqual(len(payloads), 3)
            self.assertEqual(len(info['entries']), 2)
            for name in entries:
                self.assertIn(b'/tmp/n00-ui-helpers/browser-launch-guest.sh',
                    payloads['/tmp/n00-ui-helpers/' + name])

    def test_setup_requires_original_identities_and_both_volatile_entry_mounts(self):
        info = {'helper_md5': '1' * 32, 'entries': {p: h for p, h in BROWSER.ENTRIES.values()}}
        hashes = {'/usr/bin/grob': '6162b4b46f28d53e93b9fcba7f4f3f7b',
            '/usr/lib/libQtWebKit2experimental.so.4': 'd93364105cdecaf69b53571275480d04',
            '/tmp/n00-ui-helpers/n00-browser.so': '1' * 32, **info['entries']}
        data = ('N00_BROWSER_SETUP_BEGIN\n' + ''.join(f'{h}  {p}\n' for p, h in hashes.items()) +
                ''.join(f'tmpfs {p} tmpfs rw,size=512k 0 0\n' for p in info['entries']) +
                'N00_BROWSER_SETUP_END\n').encode()
        BROWSER.validate_setup(data, info)
        for bad in (b'', data + data, data.replace(b'1' * 32, b'2' * 32),
                    data.replace(b'tmpfs ', b'ext4 ', 1),
                    data.replace(b'N00_BROWSER_SETUP_BEGIN', b''),
                    data.replace(b'6162b4b46f28d53e93b9fcba7f4f3f7b', b'0' * 32)):
            with self.assertRaises(ValueError):
                BROWSER.validate_setup(bad, info)

    def test_preparation_rejects_wrong_elf_and_binds_launch_to_helper(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binary = root / 'browser-guest/n00-browser.so'
            binary.parent.mkdir()
            data = bytearray(64); data[:7] = b'\x7fELF\x01\x01\x01'; data[16:20] = b'\x03\x00\x28\x00'
            binary.write_bytes(data)
            with patch.dict(os.environ, HARMATTAN_PREBUILT_HELPERS='', HARMATTAN_PORT_WORKSPACE=temporary), \
                    patch.object(BROWSER.subprocess, 'run'):
                payloads, info = BROWSER.prepare()
                self.assertIn(info['helper_md5'].encode(), payloads['browser-launch-guest.sh'])
                self.assertNotIn(b'@HELPER_MD5@', payloads['browser-launch-guest.sh'])
                for malformed in (b'', bytes(64), data[:16] + b'\x02\x00\x28\x00' + data[20:]):
                    binary.write_bytes(malformed)
                    with self.assertRaises(ValueError):
                        BROWSER.prepare()
