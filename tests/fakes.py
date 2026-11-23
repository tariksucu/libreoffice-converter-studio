"""A scripted transport for the API client: answers in order, and remembers every request."""

import io
import json

from converterstudio.api import ApiError, Response


class Transport:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.requests = []

    def __call__(self, method, url, headers, body, timeout):
        self.requests.append(
            {"method": method, "url": url, "headers": dict(headers), "body": body, "timeout": timeout}
        )
        if not self.answers:
            raise AssertionError("unexpected request: %s %s" % (method, url))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


class Body(io.BytesIO):
    """An answer's body as http.client reads it on Python 3.8 and 3.9 (LibreOffice 24.2's and
    24.8's own): read() or read(n), but read(-1) is refused, on whichever Python runs the tests."""

    def read(self, size=None):
        if size is not None and size < 0:
            raise ValueError("negative count")
        return super().read(size)


def reply(status=200, data=None, raw=None, headers=None):
    body = raw if raw is not None else json.dumps(data if data is not None else {}).encode()
    return Response(status, {k.lower(): v for k, v in (headers or {}).items()}, Body(body))


def error(status, code, message="", params=None):
    payload = {"code": code, "message": message}
    if params:
        payload["params"] = params
    return reply(status, {"error": payload})


def network():
    return ApiError(0, "network")
