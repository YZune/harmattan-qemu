import importlib.util
import os
from pathlib import Path
import socket
import struct
import subprocess
import tempfile
import threading
import unittest

SCRIPTS = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('splash', SCRIPTS / 'arm64-splash.py')
SPLASH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SPLASH)


def report(info, log=b''):
    lines = [b'\nN00_SPLASH_REPORT_BEGIN']
    for name in SPLASH.FILES:
        target = '/usr/bin/invoker' if name == 'invoker-direct-qemu.sh' else f'{SPLASH.HELPER_ROOT}/{name}'
        lines.append(f"{info['files'][name]['md5']}  {target}".encode())
    return b'\n'.join(lines) + b'\nN00_SPLASH_LOG_BEGIN\n' + log + b'N00_SPLASH_LOG_END\nN00_SPLASH_REPORT_END\n'


class SplashTests(unittest.TestCase):
    def test_runtime_repairs_are_not_visual_acceptance(self):
        data = (b'\nN00_ANIMATIONS_BEGIN\nN00_COMPOSITOR_SPLASH_NULL_BIND_DEFERRED\n'
                b'N00_COMPOSITOR_SPLASH_CURRENT_APP_REFRESH\nN00_ANIMATIONS_END\n')
        self.assertTrue(SPLASH.validate_repairs(data * 3)['current_app_refreshed'])
        for bad in (b'', data.replace(b'NULL_BIND_DEFERRED', b'MISSING'),
                    data.replace(b'CURRENT_APP_REFRESH', b'MISSING'),
                    data.replace(b'N00_ANIMATIONS_END', b''),
                    data + b'std::bad_alloc', data + b'N00_COMPOSITOR_SPLASH_ERROR'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                SPLASH.validate_repairs(bad)

    def test_compositor_call_scope_and_single_refresh(self):
        with tempfile.TemporaryDirectory(prefix='n00-splash-host-') as temporary:
            binary = str(Path(temporary) / 'test-splash')
            subprocess.run(['cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                            str(SCRIPTS / 'compositor-splash-guest.c'),
                            str(SCRIPTS / 'tests/compositor-splash-host.c'), '-o', binary], check=True)
            for mode in range(7):
                with self.subTest(mode=mode):
                    result = subprocess.run([binary, str(mode)], timeout=5)
                    self.assertEqual(result.returncode, 0 if mode < 3 else 125)

    def test_default_and_historical_isolation(self):
        self.assertFalse(SPLASH.enabled(None, True))
        self.assertTrue(SPLASH.enabled('on', True))
        self.assertFalse(SPLASH.enabled(None, False))
        self.assertFalse(SPLASH.enabled('off', True))
        with self.assertRaises(ValueError):
            SPLASH.enabled('unknown', True)

    def test_identity_pid_and_no_warm_splash(self):
        _, info = SPLASH.prepare()
        entry = f'N00_SPLASH_PUBLISHED pid=456 wm=00400017 portrait={SPLASH.CALC_PORTRAIT.encode().hex()} landscape=\n'.encode()
        data = report(info) * 2 + report(info, entry) * 6
        self.assertEqual(SPLASH.validate_serial(data, info, 456, 8)['publications'][0]['pid'], 456)
        for bad in (data.replace(b'pid=456', b'pid=457'), data.replace(entry, entry * 2),
                    data + report(info), data.replace(b'N00_SPLASH_REPORT_END', b''),
                    data.replace(entry, b'helper failed\n'),
                    data.replace(info['files']['N00X11.pm']['md5'].encode(), b'0' * 32)):
            with self.subTest(bad=bad[-120:]), self.assertRaises(ValueError):
                SPLASH.validate_serial(bad, info, 456, 8)

    def run_protocol(self, mode='ok', landscape=True):
        # Synthetic X11 peer tests wire types, ordering and failure handling.
        # It is not a guest, compositor, screenshot or visual PASS.
        with tempfile.TemporaryDirectory(prefix='n00-splash-') as temporary:
            directory = Path(temporary)
            portrait = directory / 'original portrait.jpg'
            other = directory / 'original landscape.jpg'
            portrait.touch(); other.touch()
            endpoint = str(directory / 'x.sock')
            server = socket.socket(socket.AF_UNIX)
            server.bind(endpoint); server.listen(1); server.settimeout(5)
            received, errors = [], []

            def exact(connection, size):
                data = b''
                while len(data) < size:
                    part = connection.recv(size - len(data))
                    if not part:
                        raise EOFError()
                    data += part
                return data

            def peer():
                try:
                    with server.accept()[0] as connection:
                        connection.settimeout(5)
                        self.assertEqual(exact(connection, 12), struct.pack('<BBHHHHH', 108, 0, 11, 0, 0, 0, 0))
                        body = bytearray(72)
                        struct.pack_into('<HHBB', body, 16, 0, 65535, 1, 0)
                        struct.pack_into('<I', body, 32, 0x44)
                        connection.sendall(struct.pack('<BBHHH', 1, 0, 11, 0, 18) + body)
                        sequence = 0
                        atoms = {'_NET_SUPPORTING_WM_CHECK': 100, '_NET_WM_CM_S0': 101, '_MEEGO_SPLASH_SCREEN': 102}
                        while True:
                            op, detail, length = struct.unpack('<BBH', exact(connection, 4))
                            payload = exact(connection, length * 4 - 4)
                            sequence += 1
                            reply = bytearray(32)
                            struct.pack_into('<BBH', reply, 0, 1, 0, sequence)
                            if op == 16:
                                self.assertEqual(detail, 1)
                                name = payload[4:4 + struct.unpack_from('<H', payload)[0]].decode()
                                struct.pack_into('<I', reply, 8, atoms[name])
                            elif op == 20:
                                window, atom, kind, offset, maximum = struct.unpack('<5I', payload)
                                self.assertEqual((atom, kind, offset, maximum), (100, 33, 0, 1000))
                                reply[1] = 32
                                struct.pack_into('<I', reply, 4, 1)
                                struct.pack_into('<III', reply, 8, 33, 0, 1)
                                reply.extend(struct.pack('<I', 0x400018 if mode == 'self' and window != 0x44 else 0x400017))
                            elif op == 23:
                                struct.pack_into('<I', reply, 8, 0 if mode == 'owner' else 0x400017)
                            elif op == 18:
                                received.append((detail, payload))
                                if mode == 'error':
                                    reply[0] = 0; reply[1] = 3
                                    connection.sendall(reply)
                                continue
                            elif op == 43 and mode == 'error':
                                # Drain the client's fence after rejecting ChangeProperty.
                                # An unused success reply can make Linux reset the socket
                                # when the client exits on the intentional X11 error.
                                return
                            elif op != 43:
                                raise AssertionError(f'unexpected opcode {op}')
                            connection.sendall(reply)
                except EOFError:
                    pass
                except Exception as error:
                    errors.append(error)

            worker = threading.Thread(target=peer)
            worker.start()
            try:
                result = subprocess.run(['perl', '-I', str(SCRIPTS), '-e',
                    'require q{' + str(SCRIPTS / 'splash-screen-guest.pl') + '}; publish(@ARGV);',
                    '456', str(portrait), str(other) if landscape else '', endpoint], capture_output=True, timeout=6)
            finally:
                worker.join(6); server.close()
            self.assertFalse(worker.is_alive())
            self.assertEqual(errors, [])
            if mode != 'ok':
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn(b'N00_SPLASH_PUBLISHED', result.stdout)
                if mode != 'error':
                    self.assertEqual(received, [])
                else:
                    self.assertEqual(len(received), 1)
                    self.assertIn(b'X11 error:', result.stderr)
                return
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(received), 1)
            detail, payload = received[0]
            window, atom, kind, fmt, count = struct.unpack_from('<IIIB3xI', payload)
            self.assertEqual((detail, window, atom, kind, fmt), (0, 0x400017, 102, 31, 8))
            self.assertEqual(payload[20:20 + count].split(b'\0'),
                [b'456', b'', os.fsencode(portrait), os.fsencode(other) if landscape else b'', b'0', b''])

    def test_original_five_strings_and_x11_fence(self):
        self.run_protocol()
        self.run_protocol(landscape=False)

    def test_wrong_wm_and_server_errors_fail(self):
        for mode in ('self', 'owner', 'error'):
            with self.subTest(mode=mode):
                self.run_protocol(mode)

    def test_invalid_inputs_do_not_connect(self):
        for args in (['0', '/missing.jpg', ''], ['1', 'relative.jpg', ''], ['1', '/missing.jpg', '']):
            result = subprocess.run(['perl', '-I', str(SCRIPTS), '-e',
                'require q{' + str(SCRIPTS / 'splash-screen-guest.pl') + '}; publish(@ARGV);', *args], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn(b'connect:', result.stderr)

    def test_invoker_preserves_arguments_when_disabled(self):
        # /bin/echo is a harmless stand-in only for argument parsing.
        result = subprocess.run(['sh', str(SCRIPTS / 'invoker-direct-qemu.sh'),
            '--splash=/a file.jpg', '-L', '/b file.jpg', '--type=m', '--', '/bin/echo', 'hello world'],
            env={**os.environ, 'N00_UI_SPLASH': '0'}, capture_output=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, b'-local-theme -graphicssystem raster hello world\n')


if __name__ == '__main__':
    unittest.main()
