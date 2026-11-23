import json
import os
import tempfile
import unittest

from converterstudio import VERSION, api
from converterstudio.api import ApiError, Canceled, Client

from .fakes import Transport, error, network, reply

BASE = "https://converter.studio/api"
KEY = "cvs_live_test_key"


def client(transport, key=KEY, sleeps=None):
    return Client(
        BASE,
        key,
        transport,
        office_version="26.8.3",
        sleep=(sleeps.append if sleeps is not None else lambda s: None),
    )


class CallTest(unittest.TestCase):
    def test_headers_of_a_keyed_call(self):
        transport = Transport(reply(200, {"plan": "pro"}))
        self.assertEqual(client(transport).account(), {"plan": "pro"})
        request = transport.requests[0]
        self.assertEqual(request["method"], "GET")
        self.assertEqual(request["url"], BASE + "/v1/account")
        headers = request["headers"]
        self.assertEqual(headers["Authorization"], "Bearer " + KEY)
        self.assertEqual(headers["X-Converter-Studio-Client"], "libreoffice/" + VERSION)
        self.assertEqual(headers["Accept"], "application/json")
        # Cloudflare turns Python's own "Python-urllib/3.x" away.
        self.assertTrue(
            headers["User-Agent"].startswith("ConverterStudio-LibreOffice/" + VERSION + " LibreOffice/26.8.3")
        )

    def test_no_key_no_request(self):
        transport = Transport()
        with self.assertRaises(ApiError) as raised:
            client(transport, key="").account()
        self.assertEqual(raised.exception.code, "noKey")
        self.assertEqual(transport.requests, [])

    def test_the_api_error_and_its_message(self):
        transport = Transport(error(401, "invalidApiKey", "This API key does not work."))
        with self.assertRaises(ApiError) as raised:
            client(transport).account()
        self.assertEqual((raised.exception.status, raised.exception.code), (401, "invalidApiKey"))
        self.assertEqual(raised.exception.message, "This API key does not work.")
        self.assertEqual(len(transport.requests), 1)

    def test_an_answer_that_is_not_the_api(self):
        for status, raw, code in (
            (200, b"<html>", "badResponse"),
            (502, b"Bad gateway", "serverBusy"),
            (302, b"", "badResponse"),
        ):
            transport = Transport(*[reply(status, raw=raw) for _ in range(4)])
            with self.assertRaises(ApiError) as raised:
                client(transport).account()
            self.assertEqual(raised.exception.code, code, status)

    def test_retries_busy_answers_with_retry_after(self):
        sleeps = []
        transport = Transport(
            reply(503, raw=b""), reply(429, {}, headers={"Retry-After": "7"}), reply(200, {"ok": True})
        )
        self.assertEqual(client(transport, sleeps=sleeps).account(), {"ok": True})
        self.assertEqual(len(transport.requests), 3)
        self.assertEqual(sleeps, [1.0, 7.0])

    def test_retries_network_errors_then_gives_up(self):
        sleeps = []
        transport = Transport(network(), network(), network(), network())
        with self.assertRaises(ApiError) as raised:
            client(transport, sleeps=sleeps).account()
        self.assertEqual(raised.exception.code, "network")
        self.assertEqual(len(transport.requests), 4)
        self.assertEqual(sleeps, [1.0, 2.0, 4.0])

    def test_convert_sends_the_same_idempotency_key_when_retried(self):
        view = {"id": "up_1", "status": "queued"}
        transport = Transport(network(), reply(201, view))
        self.assertEqual(client(transport).convert("up_1", "jpg", {"quality": "high"}, 20, "key-1"), view)
        self.assertEqual(len(transport.requests), 2)
        for request in transport.requests:
            self.assertEqual(request["method"], "POST")
            self.assertEqual(request["headers"]["Idempotency-Key"], "key-1")
            self.assertEqual(request["headers"]["Content-Type"], "application/json")
            self.assertEqual(
                json.loads(request["body"]),
                {"uploadId": "up_1", "to": "jpg", "maxCredits": 20, "options": {"quality": "high"}},
            )

    def test_convert_without_options_leaves_them_out(self):
        transport = Transport(reply(201, {"id": "x"}))
        client(transport).convert("up_1", "docx", {}, 0, "k")
        self.assertEqual(
            json.loads(transport.requests[0]["body"]), {"uploadId": "up_1", "to": "docx", "maxCredits": 0}
        )

    def test_conversion_waits_at_most_a_minute(self):
        transport = Transport(reply(200, {"id": "a/b"}), reply(200, {"id": "a/b"}))
        c = client(transport)
        c.conversion("a/b", 10)
        c.conversion("a/b", 600)
        self.assertEqual(transport.requests[0]["url"], BASE + "/v1/conversions/a%2Fb?wait=10")
        self.assertEqual(transport.requests[1]["url"], BASE + "/v1/conversions/a%2Fb?wait=60")
        self.assertEqual(transport.requests[0]["timeout"], api.TIMEOUT + 10)

    def test_confirm(self):
        transport = Transport(reply(200, {"status": "queued"}))
        client(transport).confirm("c1")
        self.assertEqual(
            (transport.requests[0]["method"], transport.requests[0]["url"]),
            ("POST", BASE + "/v1/conversions/c1/confirm"),
        )


class UploadTest(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp()
        os.write(handle, b"0123456789" * 3)
        os.close(handle)

    def tearDown(self):
        os.remove(self.path)

    def upload(self, url=BASE + "/v1/uploads/up_1?token=t", part=10):
        return {"id": "up_1", "uploadUrl": url, "partBytes": part}

    def test_sends_parts_with_their_offsets_and_without_the_key(self):
        transport = Transport(reply(200, {}), reply(200, {}), reply(200, {}))
        seen = []
        client(transport).send_file(
            self.upload(), self.path, 30, progress=lambda done, total: seen.append(done)
        )
        self.assertEqual([r["headers"]["Upload-Offset"] for r in transport.requests], ["0", "10", "20"])
        self.assertEqual([r["body"] for r in transport.requests], [b"0123456789"] * 3)
        for request in transport.requests:
            self.assertEqual(request["method"], "PUT")
            self.assertNotIn("Authorization", request["headers"])
            self.assertEqual(request["headers"]["X-Converter-Studio-Client"], "libreoffice/" + VERSION)
        self.assertEqual(seen, [0, 10, 20, 30])

    def test_goes_on_from_what_the_api_holds(self):
        transport = Transport(
            reply(200, {}),
            error(409, "uploadOffsetMismatch", "", {"received": 15}),
            reply(200, {}),
            reply(200, {}),
        )
        client(transport).send_file(self.upload(), self.path, 30)
        self.assertEqual([r["headers"]["Upload-Offset"] for r in transport.requests], ["0", "10", "15", "25"])
        self.assertEqual(transport.requests[2]["body"], b"5678901234")

    def test_refuses_an_upload_address_elsewhere(self):
        transport = Transport()
        for url in (
            "https://evil.example/upload",
            "http://converter.studio/api/v1/uploads/x",
            "https://converter.studio:444/x",
        ):
            with self.assertRaises(ApiError) as raised:
                client(transport).send_file(self.upload(url), self.path, 30)
            self.assertEqual(raised.exception.code, "unexpectedUrl")
        self.assertEqual(transport.requests, [])

    def test_stops_when_cancelled(self):
        transport = Transport(reply(200, {}))
        calls = []

        def cancelled():
            calls.append(1)
            return len(calls) > 1

        with self.assertRaises(Canceled):
            client(transport).send_file(self.upload(), self.path, 30, cancelled=cancelled)
        self.assertEqual(len(transport.requests), 1)

    def test_an_upload_error(self):
        transport = Transport(
            error(413, "fileTooLarge", "This file is larger than your plan allows (100 MB).")
        )
        with self.assertRaises(ApiError) as raised:
            client(transport).send_file(self.upload(), self.path, 30)
        self.assertEqual(raised.exception.message, "This file is larger than your plan allows (100 MB).")


class DownloadTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.target = os.path.join(self.folder, "result.jpg")

    def test_saves_the_result_without_the_key(self):
        transport = Transport(reply(200, raw=b"JPEGDATA", headers={"Content-Length": "8"}))
        size = client(transport).download("https://converter.studio/api/jobs/j/download?token=t", self.target)
        self.assertEqual(size, 8)
        with open(self.target, "rb") as handle:
            self.assertEqual(handle.read(), b"JPEGDATA")
        self.assertNotIn("Authorization", transport.requests[0]["headers"])

    def test_refuses_a_result_elsewhere(self):
        transport = Transport()
        with self.assertRaises(ApiError) as raised:
            client(transport).download("https://cdn.example/result.jpg", self.target)
        self.assertEqual(raised.exception.code, "unexpectedUrl")
        self.assertEqual(transport.requests, [])

    def test_refuses_a_result_too_large(self):
        transport = Transport(reply(200, raw=b"x" * 20))
        with self.assertRaises(ApiError) as raised:
            client(transport).download(BASE + "/jobs/j/download", self.target, max_bytes=10)
        self.assertEqual(raised.exception.code, "resultTooLarge")
        self.assertFalse(os.path.exists(self.target))
        transport = Transport(reply(200, raw=b"", headers={"Content-Length": "50"}))
        with self.assertRaises(ApiError):
            client(transport).download(BASE + "/jobs/j/download", self.target, max_bytes=10)

    def test_a_cut_download_leaves_nothing(self):
        transport = Transport(reply(200, raw=b"abc", headers={"Content-Length": "10"}))
        with self.assertRaises(ApiError) as raised:
            client(transport).download(BASE + "/jobs/j/download", self.target)
        self.assertEqual(raised.exception.code, "network")
        self.assertFalse(os.path.exists(self.target))

    def test_an_expired_result(self):
        transport = Transport(error(410, "fileExpired", "This file has expired."))
        with self.assertRaises(ApiError) as raised:
            client(transport).download(BASE + "/jobs/j/download", self.target)
        self.assertEqual(raised.exception.message, "This file has expired.")
        self.assertFalse(os.path.exists(self.target))


class ErrorsTest(unittest.TestCase):
    def test_from_view(self):
        failed = ApiError.from_view(
            {"status": "failed", "error": {"code": "noText", "message": "No text found."}}
        )
        self.assertEqual((failed.code, failed.message), ("noText", "No text found."))
        expired = ApiError.from_view({"status": "expired", "error": None})
        self.assertEqual(expired.code, "fileExpired")

    def test_from_body_with_a_bare_code(self):
        error_ = ApiError.from_body(403, json.dumps({"error": "wordpressPlanRequired"}).encode())
        self.assertEqual((error_.code, error_.message), ("wordpressPlanRequired", ""))


if __name__ == "__main__":
    unittest.main()
