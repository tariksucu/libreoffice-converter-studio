"""The real HTTP code (urllib) against a small fake API on 127.0.0.1."""

import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from converterstudio import VERSION, api, job, tls

KEY = "cvs_live_http_test"


class FakeApi(BaseHTTPRequestHandler):
    """Uploads in parts, one conversion that is processing once, then done; a redirect."""

    state = {}

    def log_message(self, *args):
        pass

    def send(self, status, data=None, raw=None, headers=None):
        body = raw if raw is not None else json.dumps(data or {}).encode()
        self.send_response(status)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def keyed(self):
        self.state.setdefault("agents", []).append(self.headers.get("User-Agent"))
        self.state.setdefault("clients", []).append(self.headers.get("X-Converter-Studio-Client"))
        if self.headers.get("Authorization") != "Bearer " + KEY:
            self.send(401, {"error": {"code": "invalidApiKey", "message": "This API key does not work."}})
            return False
        return True

    def base(self):
        return "http://127.0.0.1:%d/api" % self.server.server_address[1]

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/api/v1/account":
            if self.keyed():
                self.send(200, {"email": "a@example.com", "plan": "free", "credits": 13})
        elif path == "/api/v1/conversions/up_1":
            if self.keyed():
                self.state["polls"] = self.state.get("polls", 0) + 1
                if self.state["polls"] == 1:
                    self.send(200, {"id": "up_1", "status": "processing", "progress": 50})
                else:
                    self.send(
                        200,
                        {
                            "id": "up_1",
                            "status": "done",
                            "credits": 1,
                            "outputName": "photo.jpg",
                            "outputSize": 7,
                            "downloadUrl": self.base() + "/jobs/up_1/download?token=dl",
                        },
                    )
        elif path == "/api/jobs/up_1/download":
            self.state["download_auth"] = self.headers.get("Authorization")
            self.send(200, raw=b"JPEG!!!", headers={"Content-Type": "image/jpeg"})
        elif path == "/api/v1/moved":
            self.send(302, raw=b"", headers={"Location": "http://example.com/"})
        elif path == "/api/v1/chunked":
            # An answer without a length, in two chunks, as a proxy or server may send it.
            self.protocol_version = "HTTP/1.1"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for chunk in (b'{"plan": ', b'"free"}', b""):
                self.wfile.write(b"%x\r\n%s\r\n" % (len(chunk), chunk))
        else:
            self.send(404, {"error": {"code": "notFound", "message": "Not found."}})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        path = urlsplit(self.path).path
        if not self.keyed():
            return
        if path == "/api/v1/uploads":
            self.state["upload"] = body
            self.send(
                201,
                {
                    "id": "up_1",
                    "uploadUrl": self.base() + "/v1/uploads/up_1?token=ut",
                    "partBytes": 4,
                    "maxBytes": 100,
                },
            )
        elif path == "/api/v1/conversions":
            self.state["convert"] = body
            self.state["idempotency"] = self.headers.get("Idempotency-Key")
            self.send(201, {"id": "up_1", "status": "queued"})
        else:
            self.send(404, {"error": {"code": "notFound", "message": "Not found."}})

    def do_PUT(self):
        length = int(self.headers.get("Content-Length") or 0)
        data = self.rfile.read(length)
        self.state.setdefault("parts", []).append(
            (self.headers.get("Upload-Offset"), data, self.headers.get("Authorization"))
        )
        self.send(200, {"received": sum(len(p[1]) for p in self.state["parts"])})


class HttpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        FakeApi.state = {}
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeApi)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = "http://127.0.0.1:%d/api" % cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def client(self, key=KEY):
        return api.Client(self.base, key, api.urllib_transport(tls.make_context()), office_version="24.2.7")

    def test_a_whole_conversion(self):
        folder = tempfile.mkdtemp()
        source = os.path.join(folder, "photo.heic")
        with open(source, "wb") as handle:
            handle.write(b"0123456789")
        path, view = job.run(self.client(), source, "jpg", {}, 20, folder, sleep=lambda s: None)
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), b"JPEG!!!")
        state = FakeApi.state
        self.assertEqual(state["upload"], {"fileName": "photo.heic", "size": 10})
        self.assertEqual(
            [(offset, data) for offset, data, _ in state["parts"]],
            [("0", b"0123"), ("4", b"4567"), ("8", b"89")],
        )
        self.assertTrue(all(auth is None for _, _, auth in state["parts"]))
        self.assertEqual(state["convert"], {"uploadId": "up_1", "to": "jpg", "maxCredits": 20})
        self.assertTrue(state["idempotency"])
        self.assertIsNone(state["download_auth"])
        self.assertTrue(all(agent.startswith("ConverterStudio-LibreOffice/") for agent in state["agents"]))
        self.assertTrue(all(name == "libreoffice/" + VERSION for name in state["clients"]))
        self.assertEqual(view["status"], "done")

    def test_wrong_key(self):
        with self.assertRaises(api.ApiError) as raised:
            self.client("cvs_live_wrong").account()
        self.assertEqual((raised.exception.status, raised.exception.code), (401, "invalidApiKey"))
        self.assertEqual(raised.exception.message, "This API key does not work.")

    def test_a_chunked_answer(self):
        # From Python 3.10 until 3.12.9 and 3.13.2, read(-1) returns the chunks' framing too.
        self.assertEqual(self.client().call("GET", "/v1/chunked"), {"plan": "free"})

    def test_redirects_are_not_followed(self):
        with self.assertRaises(api.ApiError) as raised:
            self.client().call("GET", "/v1/moved")
        self.assertEqual((raised.exception.status, raised.exception.code), (302, "badResponse"))

    def test_nobody_listening(self):
        dead = api.Client(
            "http://127.0.0.1:9/api", KEY, api.urllib_transport(), sleep=lambda s: None, attempts=1
        )
        with self.assertRaises(api.ApiError) as raised:
            dead.account()
        self.assertEqual(raised.exception.code, "network")


if __name__ == "__main__":
    unittest.main()
