import os
import tempfile
import unittest

from converterstudio import job
from converterstudio.api import ApiError, Canceled


class FakeClient:
    """The API as job.run uses it, with scripted conversion states."""

    def __init__(self, states, output_name="photo.jpg", confirm_state=None):
        self.states = list(states)
        self.output_name = output_name
        self.confirm_state = confirm_state
        self.calls = []

    def create_upload(self, name, size):
        self.calls.append(("upload", name, size))
        return {
            "id": "up_1",
            "uploadUrl": "https://converter.studio/api/v1/uploads/up_1?token=t",
            "partBytes": 10,
        }

    def send_file(self, upload, path, size, progress=None, cancelled=None):
        self.calls.append(("send", path, size))
        if progress:
            progress(size, size)

    def convert(self, upload_id, to, options, max_credits, key):
        self.calls.append(("convert", upload_id, to, options, max_credits, key))
        return self.states.pop(0)

    def conversion(self, conversion_id, wait=0):
        self.calls.append(("poll", conversion_id, wait))
        return self.states.pop(0)

    def confirm(self, conversion_id):
        self.calls.append(("confirm", conversion_id))
        return self.confirm_state or self.states.pop(0)

    def download(self, url, destination, progress=None, cancelled=None):
        self.calls.append(("download", url, destination))
        with open(destination, "wb") as out:
            out.write(b"result")
        return 6


def view(status, **extra):
    base = {"id": "up_1", "status": status, "credits": 1, "progress": None}
    base.update(extra)
    return base


DONE = view(
    "done",
    downloadUrl="https://converter.studio/api/jobs/up_1/download?token=t",
    outputName="photo.jpg",
    outputSize=6,
)


class Clock:
    def __init__(self, step=2.0):
        self.now = 0.0
        self.step = step

    def __call__(self):
        self.now += self.step
        return self.now


class RunTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.source = os.path.join(self.folder, "photo.heic")
        with open(self.source, "wb") as handle:
            handle.write(b"x" * 25)
        self.out = tempfile.mkdtemp()

    def run_job(self, client, **kwargs):
        kwargs.setdefault("clock", Clock())
        kwargs.setdefault("sleep", lambda s: None)
        return job.run(client, self.source, "jpg", {}, 20, self.out, **kwargs)

    def test_upload_convert_wait_download(self):
        client = FakeClient([view("queued"), view("processing", progress=40), DONE])
        steps = []
        path, last = self.run_job(
            client, progress=lambda step, done, total: steps.append((step, done, total))
        )
        self.assertEqual(path, os.path.join(self.out, "photo.jpg"))
        self.assertEqual(last["status"], "done")
        names = [call[0] for call in client.calls]
        self.assertEqual(names, ["upload", "send", "convert", "poll", "poll", "download"])
        self.assertEqual(client.calls[0], ("upload", "photo.heic", 25))
        self.assertEqual(client.calls[2][1:5], ("up_1", "jpg", {}, 20))
        self.assertTrue(client.calls[2][5])  # an Idempotency-Key
        self.assertEqual(client.calls[3], ("poll", "up_1", job.POLL_WAIT))
        self.assertEqual([s[0] for s in steps], ["upload", "upload", "convert", "convert", "download"])
        self.assertEqual(steps[3], ("convert", 40, 100))

    def test_a_new_idempotency_key_for_each_conversion(self):
        first, second = FakeClient([DONE]), FakeClient([DONE])
        self.run_job(first)
        self.run_job(second)
        self.assertNotEqual(first.calls[2][5], second.calls[2][5])

    def test_quoted_and_confirmed(self):
        client = FakeClient([view("quoted", credits=5), DONE], confirm_state=view("queued", credits=5))
        asked = []
        path, last = self.run_job(client, confirm=lambda credits: asked.append(credits) or True)
        self.assertEqual(asked, [5])
        self.assertIn(("confirm", "up_1"), client.calls)
        self.assertEqual(last["status"], "done")

    def test_quoted_and_declined_is_never_confirmed(self):
        client = FakeClient([view("quoted", credits=5)])
        with self.assertRaises(Canceled):
            self.run_job(client, confirm=lambda credits: False)
        self.assertNotIn("confirm", [call[0] for call in client.calls])
        with self.assertRaises(Canceled):
            self.run_job(FakeClient([view("quoted", credits=5)]))

    def test_a_failed_conversion_gives_the_api_reason(self):
        client = FakeClient(
            [
                view("processing"),
                view("failed", error={"code": "noText", "message": "We couldn't find any text."}),
            ]
        )
        with self.assertRaises(ApiError) as raised:
            self.run_job(client)
        self.assertEqual(
            (raised.exception.code, raised.exception.message), ("noText", "We couldn't find any text.")
        )
        self.assertNotIn("download", [call[0] for call in client.calls])

    def test_expired_and_canceled(self):
        for status, code in (("expired", "fileExpired"), ("canceled", "conversionFailed")):
            with self.assertRaises(ApiError) as raised:
                self.run_job(FakeClient([view(status, error=None)]))
            self.assertEqual(raised.exception.code, code)

    def test_cancelled_before_uploading(self):
        client = FakeClient([DONE])
        with self.assertRaises(Canceled):
            self.run_job(client, cancelled=lambda: True)
        self.assertEqual(client.calls, [])

    def test_cancelled_after_the_upload(self):
        client = FakeClient([DONE])
        with self.assertRaises(Canceled):
            self.run_job(client, cancelled=lambda: len(client.calls) >= 2)
        self.assertEqual([call[0] for call in client.calls], ["upload", "send"])

    def test_gives_up_after_the_deadline(self):
        client = FakeClient([view("processing")] * 5)
        with self.assertRaises(ApiError) as raised:
            self.run_job(client, clock=Clock(step=1000), deadline=2500)
        self.assertEqual(raised.exception.code, "timeout")

    def test_pauses_when_the_server_answers_at_once(self):
        sleeps = []
        client = FakeClient([view("queued"), view("processing"), DONE])
        self.run_job(client, clock=Clock(step=0.1), sleep=sleeps.append)
        self.assertEqual(sleeps, [1])

    def test_empty_file(self):
        open(self.source, "wb").close()
        with self.assertRaises(ApiError) as raised:
            self.run_job(FakeClient([DONE]))
        self.assertEqual(raised.exception.code, "emptyFile")

    def test_result_names_stay_in_the_work_folder(self):
        evil = dict(DONE, outputName="../../outside.jpg")
        path, _ = self.run_job(FakeClient([evil]))
        self.assertEqual(path, os.path.join(self.out, "outside.jpg"))
        nameless = dict(DONE, outputName=None)
        path, _ = self.run_job(FakeClient([nameless]))
        self.assertEqual(path, os.path.join(self.out, "photo.jpg"))

    def test_done_without_a_result(self):
        with self.assertRaises(ApiError) as raised:
            self.run_job(FakeClient([dict(DONE, downloadUrl=None)]))
        self.assertEqual(raised.exception.code, "noResult")


if __name__ == "__main__":
    unittest.main()
