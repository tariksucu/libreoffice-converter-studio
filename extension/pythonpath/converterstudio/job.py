"""One conversion from start to finish: upload, convert, wait, download.

Runs without LibreOffice: the caller passes what to do on progress, how to tell it was cancelled,
and how to ask when a file costs more credits than allowed.
"""

import os
import time
import uuid

from .api import FINAL, ApiError, Canceled
from .formats import safe_file_name

# Seconds the API may hold one status request open while it waits for the conversion.
POLL_WAIT = 10

# A conversion that takes longer than this is given up (the API keeps working; nothing is lost
# but the wait). Long scans can take minutes; an hour is far beyond any document or picture.
DEADLINE = 3600


class Steps:
    """Where the work is, for the progress dialog."""

    UPLOAD = "upload"
    CONVERT = "convert"
    DOWNLOAD = "download"


def run(
    client,
    path,
    to,
    options,
    max_credits,
    workdir,
    progress=None,
    cancelled=None,
    confirm=None,
    clock=time.monotonic,
    sleep=time.sleep,
    poll_wait=POLL_WAIT,
    deadline=DEADLINE,
):
    """Converts the file at `path` to `to`; returns (result path, the conversion's last state).

    `progress(step, done, total)` is told how far it got; `cancelled()` is asked between steps;
    `confirm(credits)` is asked when the price is above `max_credits` and returns True to go on.
    """
    report = progress or (lambda step, done, total: None)
    stop = cancelled or (lambda: False)

    def check():
        if stop():
            raise Canceled()

    name = os.path.basename(path)
    size = os.path.getsize(path)
    if size <= 0:
        raise ApiError(0, "emptyFile")
    check()
    report(Steps.UPLOAD, 0, size)
    upload = client.create_upload(name, size)
    client.send_file(upload, path, size, lambda done, total: report(Steps.UPLOAD, done, total), stop)
    check()

    # The same key on a repeated request (a lost answer) returns the first conversion: one job,
    # one charge.
    view = client.convert(upload["id"], to, options, max_credits, str(uuid.uuid4()))
    conversion_id = view["id"]
    started = clock()
    confirmed = False
    while True:
        status = view.get("status")
        if status == "done":
            break
        if status in FINAL:
            raise ApiError.from_view(view)
        if status == "quoted" and not confirmed:
            if not confirm or not confirm(view.get("credits")):
                raise Canceled()
            confirmed = True
            view = client.confirm(conversion_id)
            continue
        check()
        if clock() - started > deadline:
            raise ApiError(0, "timeout")
        report(Steps.CONVERT, view.get("progress") or 0, 100)
        asked = clock()
        view = client.conversion(conversion_id, poll_wait)
        # A server that answers at once (no long poll) is asked again after a short pause.
        if view.get("status") not in FINAL and clock() - asked < 1:
            sleep(1)

    check()
    url = view.get("downloadUrl")
    if not url:
        raise ApiError(0, "noResult")
    fallback = os.path.splitext(name)[0] + "." + to
    target = os.path.join(
        workdir, safe_file_name(view.get("outputName"), safe_file_name(fallback, "result." + to))
    )
    report(Steps.DOWNLOAD, 0, view.get("outputSize") or 0)
    client.download(url, target, lambda done, total: report(Steps.DOWNLOAD, done, total), stop)
    return target, view
