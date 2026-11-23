"""The extension's settings: their defaults and how what the user types is checked."""

from urllib.parse import urlsplit

from . import DEFAULT_BASE_URL

DEFAULT_MAX_CREDITS = 20
MAX_CREDITS_LIMIT = 100000

# Languages the API recognises text in (its `ocrLanguage` option), "auto" first.
OCR_LANGUAGES = (
    "auto",
    "en",
    "tr",
    "de",
    "fr",
    "es",
    "it",
    "pt",
    "nl",
    "pl",
    "cs",
    "ru",
    "el",
    "ar",
    "he",
    "hi",
    "zh",
    "ja",
    "ko",
    "vi",
)

# What a text recognition gives: a new document, or plain text at the cursor.
OCR_OUTPUTS = ("document", "text")

DEFAULTS = {
    "BaseUrl": DEFAULT_BASE_URL,
    "MaxCredits": DEFAULT_MAX_CREDITS,
    "OcrLanguage": "auto",
    "OcrOutput": "document",
}

# Hosts where plain http is allowed: a Converter Studio test server on this computer.
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


class SettingError(ValueError):
    """A value that cannot be used; `code` names the message to show."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def normalize_base_url(value):
    """The API's address without a trailing slash; https, or http on this computer only."""
    text = (value or "").strip()
    if not text:
        return DEFAULT_BASE_URL
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError:
        raise SettingError("badBaseUrl")
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("https", "http") or not host:
        raise SettingError("badBaseUrl")
    if parts.username is not None or parts.password is not None or parts.query or parts.fragment:
        raise SettingError("badBaseUrl")
    if parts.scheme == "http" and host not in LOCAL_HOSTS:
        raise SettingError("httpsOnly")
    netloc = ("[%s]" % host if ":" in host else host) + (":%d" % port if port else "")
    return "%s://%s%s" % (parts.scheme, netloc, parts.path.rstrip("/"))


def normalize_key(value):
    """The API key as pasted, without surrounding spaces; '' when empty."""
    key = (value or "").strip()
    if not key:
        return ""
    if len(key) > 256 or any(c.isspace() or ord(c) < 33 or ord(c) > 126 for c in key):
        raise SettingError("badKey")
    return key


def normalize_max_credits(value):
    """Credits a file may cost without asking: a whole number from 0 (always ask)."""
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return DEFAULT_MAX_CREDITS
    return max(0, min(MAX_CREDITS_LIMIT, number))


def normalize_language(value):
    return value if value in OCR_LANGUAGES else "auto"


def normalize_output(value):
    return value if value in OCR_OUTPUTS else "document"


def normalize(values):
    """Every setting, checked, with defaults for what is missing (the base URL may raise)."""
    merged = dict(DEFAULTS)
    merged.update({k: v for k, v in (values or {}).items() if v is not None})
    return {
        "BaseUrl": normalize_base_url(merged["BaseUrl"]),
        "MaxCredits": normalize_max_credits(merged["MaxCredits"]),
        "OcrLanguage": normalize_language(merged["OcrLanguage"]),
        "OcrOutput": normalize_output(merged["OcrOutput"]),
    }


def site_of(base_url):
    """The website an API address belongs to (for links): ".../api" without "/api"."""
    return base_url[: -len("/api")] if base_url.endswith("/api") else base_url
