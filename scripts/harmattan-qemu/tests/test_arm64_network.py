import hashlib
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[3]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts/harmattan-qemu' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


NETWORK = load('arm64-network')
SMOKE = load('smoke-arm64-network')
SETUP = (b'N00_NETWORK_LEASE ip=10.0.2.15 mask=255.255.255.0 router=10.0.2.2 dns=10.0.2.3\n'
         b'N00_NETWORK_READY\nN00_NETWORK_EXIT_0\nN00_NETWORK_FINISHED\n')


class NetworkTests(unittest.TestCase):
    def test_one_successful_lease_is_required(self):
        result = NETWORK.validate_setup(SETUP.replace(b'\n', b'\r\n'))
        self.assertTrue(result['dhcp'])
        for bad in (b'', SETUP.replace(b'10.0.2.15', b'192.168.1.10'),
                    SETUP.replace(b'N00_NETWORK_EXIT_0', b'N00_NETWORK_EXIT_1'),
                    SETUP + b'N00_NETWORK_EXIT_2\n', SETUP + SETUP,
                    SETUP.replace(b'N00_NETWORK_READY\n', b'')):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                NETWORK.validate_setup(bad)

    def test_bidirectional_bytes_must_match(self):
        payload = bytes(range(256)) * 256
        digest = hashlib.md5(payload).hexdigest()
        serial = (f'N00_NETWORK_DNS 93.184.215.14\n{digest}  /tmp/n00-network-download\n'
                  'N00_NETWORK_INTERNET_HTTP_200 500\nN00_NETWORK_TRANSFER_EXIT_0\n').encode()
        self.assertEqual(SMOKE.validate_transfer(serial, digest, [payload])['bytes_each_way'], 65536)
        for data, uploads in ((serial, []), (serial, [payload[:-1]]),
                              (serial, [payload, payload]), (serial + serial, [payload]),
                              (serial.replace(digest.encode(), b'0' * 32), [payload]),
                              (serial.replace(b'EXIT_0', b'EXIT_1'), [payload]),
                              (serial + b'N00_NETWORK_TRANSFER_EXIT_1\n', [payload]),
                              (serial.replace(b'N00_NETWORK_DNS', b'/ # N00_NETWORK_DNS'), [payload]),
                              (serial.replace(b'93.184.215.14', b'999.0.0.1'), [payload]),
                              (serial.replace(b'HTTP_200', b'HTTP_503'), [payload]),
                              (serial.replace(b'HTTP_200 500', b'HTTP_200 0'), [payload]),
                              (serial.replace(b'HTTP_200 500', b'HTTP_200 1048577'), [payload])):
            with self.subTest(data=data, uploads=len(uploads)), self.assertRaises(ValueError):
                SMOKE.validate_transfer(data, digest, uploads)


if __name__ == '__main__':
    unittest.main()
