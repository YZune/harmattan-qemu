import hashlib
import importlib.util
from pathlib import Path
import ssl
from types import SimpleNamespace
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location('certificates', Path(__file__).resolve().parents[1] / 'arm64-certificates.py')
CA = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CA)


class CertificateTests(unittest.TestCase):
    def test_export_preserves_the_host_tls_trust_anchors(self):
        expected = set(ssl.create_default_context().get_ca_certs(binary_form=True))
        if not expected:
            self.skipTest('host Python has no installed CA trust store')
        payload, info = CA.host_store()
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.load_verify_locations(cadata=payload.decode('ascii'))
        self.assertEqual(set(context.get_ca_certs(binary_form=True)), expected)
        self.assertEqual(info['count'], len(expected))
        self.assertEqual(info['sha256'], hashlib.sha256(payload).hexdigest())
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        self.assertNotIn(b'PRIVATE KEY', payload)

    def test_empty_oversized_and_malformed_store_fail(self):
        for certificates in ([], [b'bad'], [b'x' * 32769], [b'x' * 128]):
            context = SimpleNamespace(get_ca_certs=lambda binary_form: certificates)
            with self.subTest(certificates=certificates), patch.object(CA.ssl, 'create_default_context', return_value=context):
                with self.assertRaises((ValueError, ssl.SSLError)):
                    CA.host_store()

    def test_guest_requires_exact_bytes_count_and_volatile_mount(self):
        info = {'md5': '1' * 32, 'count': 193}
        data = (b'N00_CA_REPORT_BEGIN\n' + b'1' * 32 + b'  /etc/ssl/certs/ca.pem\n193\n'
                b'tmpfs /etc/ssl/certs tmpfs rw,relatime,size=3072k 0 0\n'
                b'N00_CA_REPORT_END\n'
                b'N00_CA_CHECK_EXIT_0\n')
        CA.validate_install(data, info)
        for bad in (b'', data + data, data.replace(b'193', b'192'),
                    data.replace(b'1' * 32, b'2' * 32),
                    data.replace(b'tmpfs /etc/ssl/certs tmpfs', b'/dev/root /etc/ssl/certs ext4'),
                    data.replace(b'N00_CA_REPORT_BEGIN\n', b'').replace(b'N00_CA_REPORT_END',
                        b'N00_CA_REPORT_BEGIN\nN00_CA_REPORT_END'),
                    data.replace(b'N00_CA_CHECK_EXIT_0', b'N00_CA_CHECK_EXIT_1')):
            with self.subTest(data=bad), self.assertRaises(ValueError):
                CA.validate_install(bad, info)


if __name__ == '__main__':
    unittest.main()
