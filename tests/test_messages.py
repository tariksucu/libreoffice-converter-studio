import os
import re
import tempfile
import unittest

from converterstudio import messages
from converterstudio.api import ApiError
from converterstudio.messages import Catalog

PLACEHOLDER = re.compile(r"\{(\w+)\}")


def load(language):
    with open(os.path.join(messages.HERE, language + ".properties"), encoding="utf-8") as handle:
        return messages.parse(handle.read())


class ParseTest(unittest.TestCase):
    def test_parse(self):
        text = "# comment\n\nplain = Hello\nwith.equals = a = b\nescaped = one\\ntwo\\\\three\nnot a pair\n"
        self.assertEqual(
            messages.parse(text),
            {"plain": "Hello", "with.equals": "a = b", "escaped": "one\ntwo\\three"},
        )


class LanguagesTest(unittest.TestCase):
    def test_every_language_has_every_text_with_the_same_placeholders(self):
        english = load("en")
        self.assertIn("tr", messages.available())
        for language in messages.available():
            texts = load(language)
            self.assertEqual(set(texts), set(english), language)
            for key, value in english.items():
                self.assertEqual(
                    set(PLACEHOLDER.findall(texts[key])), set(PLACEHOLDER.findall(value)), (language, key)
                )

    def test_every_ocr_language_and_error_code_has_a_text(self):
        from converterstudio import settings

        english = load("en")
        for code in settings.OCR_LANGUAGES:
            self.assertIn("lang." + code, english)
        for code in (
            "network",
            "tls",
            "badResponse",
            "serverBusy",
            "unexpectedUrl",
            "resultTooLarge",
            "emptyFile",
            "timeout",
            "noResult",
            "noKey",
            "badBaseUrl",
            "httpsOnly",
            "badKey",
        ):
            self.assertIn("error." + code, english)

    def test_best_language(self):
        languages = ["en", "pt-BR", "tr"]
        self.assertEqual(messages.best_language("tr-TR", languages), "tr")
        self.assertEqual(messages.best_language("pt_BR", languages), "pt-BR")
        self.assertEqual(messages.best_language("de-DE", languages), "en")
        self.assertEqual(messages.best_language("", languages), "en")


class CatalogTest(unittest.TestCase):
    def test_turkish_with_english_behind_it(self):
        folder = tempfile.mkdtemp()
        with open(os.path.join(folder, "en.properties"), "w", encoding="utf-8") as handle:
            handle.write("a = A\nb = B {n}\n")
        with open(os.path.join(folder, "tr.properties"), "w", encoding="utf-8") as handle:
            handle.write("a = Ä\n")
        catalog = Catalog("tr-TR", folder)
        self.assertEqual(catalog.language, "tr")
        self.assertEqual(catalog.get("a"), "Ä")
        self.assertEqual(catalog.get("b", n=3), "B 3")
        self.assertEqual(catalog.get("missing"), "missing")
        self.assertEqual(catalog.get("b", other=1), "B {n}")

    def test_real_catalogs(self):
        self.assertEqual(Catalog("tr-TR").get("cancel"), "Vazgeç")
        self.assertEqual(Catalog("fr-FR").get("cancel"), "Cancel")


class ErrorTextTest(unittest.TestCase):
    def setUp(self):
        self.catalog = Catalog("en-US")

    def test_the_api_message_comes_first(self):
        error = ApiError(401, "invalidApiKey", "This API key does not work.")
        self.assertEqual(messages.error_text(self.catalog, error), "This API key does not work.")

    def test_our_text_for_our_codes(self):
        self.assertIn("could not be reached", messages.error_text(self.catalog, ApiError(0, "network")))
        self.assertIn("certificate", messages.error_text(self.catalog, ApiError(0, "tls")))

    def test_unknown_code(self):
        self.assertEqual(
            messages.error_text(self.catalog, ApiError(418, "teapot")), "Something went wrong (teapot)."
        )

    def test_credit_count(self):
        self.assertEqual(messages.credit_count(self.catalog, 1), "1 credit")
        self.assertEqual(messages.credit_count(self.catalog, 0), "0 credits")
        self.assertEqual(messages.credit_count(self.catalog, 12), "12 credits")
        self.assertEqual(messages.credit_count(self.catalog, None), "?")
        self.assertEqual(messages.credit_count(Catalog("tr"), 12), "12 kredi")

    def test_human_size(self):
        self.assertEqual(messages.human_size(999), "999 B")
        self.assertEqual(messages.human_size(1536), "1.5 KB")
        self.assertEqual(messages.human_size(12_400_000), "12.4 MB")
        self.assertEqual(messages.human_size(3 * 10**12), "3000.0 GB")


if __name__ == "__main__":
    unittest.main()
