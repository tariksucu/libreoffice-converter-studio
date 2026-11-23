#!/usr/bin/env python3
"""Installs the built extension into a throwaway LibreOffice profile and checks that LibreOffice
loads it: the service starts, the settings check what they get, and nothing is sent without a key.
No request leaves the computer.

    python3 tools/build.py
    python3 tools/smoke.py dist/converter-studio-<version>.oxt [path to soffice's program folder]

Needs LibreOffice with Python-UNO (Debian, Ubuntu: libreoffice-writer-nogui python3-uno) and a
Python that can `import uno` (the system's on Linux distributions).
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time

import uno
from com.sun.star.beans import NamedValue, PropertyValue

OXT = os.path.abspath(sys.argv[1])
PROGRAM = sys.argv[2] if len(sys.argv) > 2 else "/usr/lib/libreoffice/program"
PIPE = "cvs-smoke-%d" % os.getpid()


def main():
    profile = tempfile.mkdtemp(prefix="cvs-smoke-profile-")
    env = "-env:UserInstallation=" + uno.systemPathToFileUrl(profile)
    failures = []

    def check(name, condition, detail=""):
        print("%s %s%s" % ("ok  " if condition else "FAIL", name, "" if condition else ": %s" % (detail,)))
        if not condition:
            failures.append(name)

    installed = subprocess.run(
        [os.path.join(PROGRAM, "unopkg"), "add", env, OXT], input=b"yes\n", capture_output=True, timeout=300
    )
    check("unopkg add (licence accepted)", installed.returncode == 0, installed.stderr.decode()[-400:])
    office = subprocess.Popen(
        [
            os.path.join(PROGRAM, "soffice"),
            env,
            "--headless",
            "--norestore",
            "--nodefault",
            "--accept=pipe,name=%s;urp;" % PIPE,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        local = uno.getComponentContext()
        resolver = local.ServiceManager.createInstanceWithContext("com.sun.star.bridge.UnoUrlResolver", local)
        ctx = None
        for _ in range(240):
            try:
                ctx = resolver.resolve("uno:pipe,name=%s;urp;StarOffice.ComponentContext" % PIPE)
                break
            except Exception:
                time.sleep(0.5)
        check("LibreOffice answers", ctx is not None)
        if ctx is None:
            return 1
        smgr = ctx.ServiceManager
        service = smgr.createInstanceWithContext("studio.converter.libreoffice.Commands", ctx)
        check("the extension's service starts", service is not None)

        def run(**args):
            result = service.execute(tuple(NamedValue(k, v) for k, v in args.items()))
            return {item.Name: item.Value for item in result}

        r = run(Command="configure", BaseUrl="http://example.com/api")
        check("plain http to another computer is refused", r.get("Code") == "httpsOnly", r)
        r = run(Command="account")
        check("without a key nothing is sent", r.get("Code") == "noKey", r)
        desktop = smgr.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)
        writer = desktop.loadComponentFromURL(
            "private:factory/swriter", "_blank", 0, (PropertyValue(Name="Hidden", Value=True),)
        )
        r = run(Command="insertPicture", File=os.path.abspath(__file__), Document=writer)
        check("a file the command does not take is refused", r.get("Code") == "unsupported", r)
        writer.close(True)
        try:
            desktop.terminate()
        except Exception:
            pass
    finally:
        try:
            office.wait(timeout=30)
        except subprocess.TimeoutExpired:
            office.kill()
        shutil.rmtree(profile, ignore_errors=True)
    print("%d failed" % len(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
