import os
import ssl
import unittest
from unittest import mock

from converterstudio import tls

SYSTEM_BUNDLE = next((path for path in tls.CA_FILES if os.path.isfile(path)), None)


def empty_context():
    """What LibreOffice's own Python builds start with: OpenSSL without any authority."""
    return ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


class ContextTest(unittest.TestCase):
    @unittest.skipIf(SYSTEM_BUNDLE is None, "no system certificate bundle here")
    def test_adds_the_system_bundle_when_there_is_none(self):
        with mock.patch.object(ssl, "create_default_context", empty_context), mock.patch.dict(
            os.environ, {}, clear=False
        ):
            os.environ.pop("SSL_CERT_FILE", None)
            context = tls.make_context()
        self.assertGreater(tls.authorities(context), 0)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)

    def test_skips_missing_and_broken_bundles(self):
        broken = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_tls.py")
        with mock.patch.object(ssl, "create_default_context", empty_context), mock.patch.dict(
            os.environ, {}, clear=False
        ):
            os.environ.pop("SSL_CERT_FILE", None)
            context = tls.make_context(ca_files=("/nonexistent/ca.pem", broken))
        self.assertEqual(tls.authorities(context), 0)
        # Still verifying: an unknown certificate fails rather than passes.
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)

    def test_respects_ssl_cert_file(self):
        with mock.patch.object(ssl, "create_default_context", empty_context), mock.patch.dict(
            os.environ, {"SSL_CERT_FILE": "/x.pem"}
        ):
            context = tls.make_context(exists=lambda path: self.fail("should not look"))
        self.assertEqual(tls.authorities(context), 0)

    def test_keeps_a_working_default(self):
        context = ssl.create_default_context()
        if tls.authorities(context) == 0:
            self.skipTest("this Python has no default authorities")
        calls = []
        tls.make_context(exists=lambda path: calls.append(path) or False)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
