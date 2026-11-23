"""Which files each command takes, and what Converter Studio turns them into.

Only what LibreOffice cannot do itself: it does not open HEIC, AVIF or camera RAW pictures (24.2
and 26.8 read them as text), has no text recognition, and does not open EPUB, MOBI or AZW3 books.
"""

import os

# Pictures LibreOffice cannot open -> the format they are inserted as. AVIF may be see-through,
# so it becomes PNG; photos become JPG.
PICTURES = {
    "heic": "jpg",
    "heif": "jpg",
    "avif": "png",
    "cr2": "jpg",
    "nef": "jpg",
    "arw": "jpg",
    "dng": "jpg",
}

# Scans and photos whose text can be recognised (the API's OCR sources, and PDF).
OCR_IMAGES = ("jpg", "jpeg", "png", "webp", "heic", "heif", "tif", "tiff", "bmp")
OCR_SOURCES = ("pdf",) + OCR_IMAGES

# E-books LibreOffice cannot open -> a Word document it can.
EBOOKS = ("epub", "mobi", "azw3")

# File-picker filters: (message key, extensions).
PICTURE_FILTERS = (
    ("filterPictures", tuple(PICTURES)),
    ("filterHeic", ("heic", "heif")),
    ("filterAvif", ("avif",)),
    ("filterRaw", ("cr2", "nef", "arw", "dng")),
)
OCR_FILTERS = (
    ("filterScans", OCR_SOURCES),
    ("filterPdf", ("pdf",)),
    ("filterImages", OCR_IMAGES),
)
EBOOK_FILTERS = (("filterEbooks", EBOOKS),)


def extension(name):
    """The file's extension, lower case, without the dot ('' when it has none)."""
    return os.path.splitext(name or "")[1][1:].lower()


def patterns(extensions):
    """A file-picker pattern such as "*.heic;*.HEIC" (both cases: some pickers match exactly)."""
    out = []
    for ext in extensions:
        out.extend(("*." + ext, "*." + ext.upper()))
    return ";".join(out)


class Unsupported(ValueError):
    """The file is not one this command takes."""


def picture_request(name):
    """(to, options) for a picture to insert."""
    to = PICTURES.get(extension(name))
    if not to:
        raise Unsupported(name)
    # The camera's details and location stay out of the document (the API's default too).
    return to, {}


def ocr_request(name, language="auto", output="document"):
    """(to, options) to recognise the text of a scan: a Word document or plain text."""
    ext = extension(name)
    if ext not in OCR_SOURCES:
        raise Unsupported(name)
    to = "txt" if output == "text" else "docx"
    options = {"ocrLanguage": language or "auto"}
    if ext == "pdf":
        # A PDF is otherwise read for the text it carries; scans carry none.
        options["ocr"] = True
    return to, options


def ebook_request(name):
    """(to, options) to open an e-book as a document."""
    if extension(name) not in EBOOKS:
        raise Unsupported(name)
    return "docx", {}


def fit(size, area):
    """`size` made smaller, keeping its proportions, until it fits in `area` (never larger)."""
    width, height = max(1, size[0]), max(1, size[1])
    scale = min(1.0, area[0] / float(width), area[1] / float(height))
    return max(1, int(width * scale)), max(1, int(height * scale))


def safe_file_name(name, fallback):
    """A file name to save a result under: no folders, no control characters, not too long."""
    base = os.path.basename((name or "").replace("\\", "/"))
    base = "".join(c for c in base if c.isprintable() and c not in '<>:"/\\|?*').strip(" .")
    if not base:
        base = fallback
    root, ext = os.path.splitext(base)
    return root[: 120 - len(ext)] + ext
