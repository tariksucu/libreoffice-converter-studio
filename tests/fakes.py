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


def reply(status=200, data=None, raw=None, headers=None):
    body = raw if raw is not None else json.dumps(data if data is not None else {}).encode()
    return Response(status, {k.lower(): v for k, v in (headers or {}).items()}, io.BytesIO(body))


def error(status, code, message="", params=None):
    payload = {"code": code, "message": message}
    if params:
        payload["params"] = params
    return reply(status, {"error": payload})


def network():
    return ApiError(0, "network")
