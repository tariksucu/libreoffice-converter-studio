"""The extension's texts, one UTF-8 `.properties` file per language in `l10n/`.

A file has `key = value` lines; `#` starts a comment; `\\n` is a new line. `{name}` in a value is
filled in when the text is used. A text missing from a language falls back to English.
"""

import os

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "l10n")
FALLBACK = "en"


def parse(text):
    """The key -> value pairs of a .properties text."""
    out = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = _unescape(value.strip())
    return out


def _unescape(value):
    result = []
    i = 0
    while i < len(value):
        c = value[i]
        if c == "\\" and i + 1 < len(value):
            nxt = value[i + 1]
            result.append({"n": "\n", "t": "\t", "\\": "\\"}.get(nxt, nxt))
            i += 2
            continue
        result.append(c)
        i += 1
    return "".join(result)


def available(folder=HERE):
    """The languages there are files for ("en", "tr"…)."""
    return sorted(name[: -len(".properties")] for name in os.listdir(folder) if name.endswith(".properties"))


def best_language(locale, languages):
    """The language to show for a LibreOffice locale ("tr-TR" -> "tr", "pt-BR" -> "pt-BR" or "pt")."""
    tag = (locale or "").replace("_", "-")
    if tag in languages:
        return tag
    primary = tag.split("-")[0].lower()
    return primary if primary in languages else FALLBACK


class Catalog:
    """The texts of one language, with English behind them."""

    def __init__(self, locale="en", folder=HERE):
        self.language = best_language(locale, available(folder))
        self._texts = self._load(folder, FALLBACK)
        if self.language != FALLBACK:
            self._texts.update(self._load(folder, self.language))

    @staticmethod
    def _load(folder, language):
        path = os.path.join(folder, language + ".properties")
        try:
            with open(path, encoding="utf-8") as handle:
                return parse(handle.read())
        except OSError:
            return {}

    def has(self, key):
        return key in self._texts

    def get(self, key, **params):
        """The text for `key`, filled in; the key itself when there is none."""
        text = self._texts.get(key, key)
        if params:
            try:
                return text.format_map(_Defaulting(params))
            except (ValueError, IndexError):
                return text
        return text


def error_text(catalog, error):
    """What to tell the user about a failed request: the API's own sentence when it sent one,
    else ours for the code."""
    message = getattr(error, "message", "")
    if message:
        return message
    code = getattr(error, "code", "") or "other"
    key = "error." + code
    if catalog.has(key):
        return catalog.get(key, detail=str(error))
    return catalog.get("error.other", code=code)


def credit_count(catalog, credits):
    """ "1 credit", "5 credits" ("?" when the price is not known)."""
    if credits is None:
        return "?"
    return catalog.get("credit.one" if credits == 1 else "credit.other", n=credits)


def human_size(size):
    """1536 -> "1.5 KB" (decimal units, like the API's own limits)."""
    value = float(size or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1000 or unit == "GB":
            return ("%d %s" % (value, unit)) if unit == "B" else ("%.1f %s" % (value, unit))
        value /= 1000.0
    return "%d B" % size


class _Defaulting(dict):
    """Leaves an unknown {name} as it is instead of failing."""

    def __missing__(self, key):
        return "{" + key + "}"
