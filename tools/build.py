#!/usr/bin/env python3
"""Builds the extension: dist/converter-studio-<version>.oxt from extension/.

    python3 tools/build.py            # builds, after checking the package (see check())
    python3 tools/build.py --check    # only checks

An .oxt is a ZIP. The same sources always give the same bytes (fixed dates, sorted names).
"""

import os
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, "extension")
DIST = os.path.join(ROOT, "dist")
FEED = os.path.join(ROOT, "update", "converter-studio.update.xml")

NS = {
    "d": "http://openoffice.org/extensions/description/2006",
    "u": "http://openoffice.org/extensions/update/2006",
    "m": "http://openoffice.org/2001/manifest",
    "xlink": "http://www.w3.org/1999/xlink",
}
SKIP_DIRS = {"__pycache__"}
SKIP_SUFFIXES = (".pyc", ".pyo", ".orig", ".swp", "~")


def files():
    """The extension's files, relative to extension/, sorted."""
    out = []
    for folder, dirs, names in os.walk(SOURCE):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        for name in names:
            if name.startswith(".") or name.endswith(SKIP_SUFFIXES):
                continue
            out.append(os.path.relpath(os.path.join(folder, name), SOURCE).replace(os.sep, "/"))
    return sorted(out)


def version():
    tree = ET.parse(os.path.join(SOURCE, "description.xml"))
    return tree.getroot().find("d:version", NS).get("value")


def check():
    """Problems that would make LibreOffice refuse or misbehave; an empty list when none."""
    problems = []
    present = set(files())
    for name in sorted(present):
        if name.endswith((".xml", ".xcu", ".xcs", ".components")):
            try:
                ET.parse(os.path.join(SOURCE, name))
            except ET.ParseError as error:
                problems.append("%s: not well-formed XML (%s)" % (name, error))
    manifest = ET.parse(os.path.join(SOURCE, "META-INF", "manifest.xml")).getroot()
    for entry in manifest.findall("m:file-entry", NS):
        path = entry.get("{%s}full-path" % NS["m"])
        if path not in present:
            problems.append("manifest.xml names a missing file: " + path)
    description = ET.parse(os.path.join(SOURCE, "description.xml")).getroot()
    for element in description.iter():
        href = element.get("{%s}href" % NS["xlink"])
        if href and not re.match(r"^[a-z]+://", href) and href not in present:
            problems.append("description.xml names a missing file: " + href)
    value = version()
    if not re.match(r"^\d+\.\d+\.\d+$", value or ""):
        problems.append("description.xml: the version is not x.y.z: %r" % value)
    with open(
        os.path.join(SOURCE, "pythonpath", "converterstudio", "__init__.py"), encoding="utf-8"
    ) as handle:
        init = handle.read()
    match = re.search(r'^VERSION = "([^"]+)"', init, re.M)
    if not match or match.group(1) != value:
        problems.append("converterstudio.VERSION differs from description.xml (%s)" % value)
    feed = ET.parse(FEED).getroot()
    if feed.find("u:version", NS).get("value") != value:
        problems.append("update feed: the version differs from description.xml (%s)" % value)
    if feed.find("u:identifier", NS).get("value") != description.find("d:identifier", NS).get("value"):
        problems.append("update feed: the identifier differs from description.xml")
    download = feed.find("u:update-download/u:src", NS).get("{%s}href" % NS["xlink"])
    if "v%s/" % value not in download or not download.endswith("-%s.oxt" % value):
        problems.append("update feed: the download is not this version's: " + download)
    return problems


def build():
    problems = check()
    if problems:
        for problem in problems:
            print("error: " + problem, file=sys.stderr)
        return 1
    os.makedirs(DIST, exist_ok=True)
    target = os.path.join(DIST, "converter-studio-%s.oxt" % version())
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in files():
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            with open(os.path.join(SOURCE, name), "rb") as handle:
                archive.writestr(info, handle.read())
    print(target)
    return 0


if __name__ == "__main__":
    if "--check" in sys.argv[1:]:
        found = check()
        for item in found:
            print("error: " + item, file=sys.stderr)
        sys.exit(1 if found else 0)
    sys.exit(build())
