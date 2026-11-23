import unittest

from converterstudio import DEFAULT_BASE_URL, settings
from converterstudio.settings import SettingError


class BaseUrlTest(unittest.TestCase):
    def test_default_when_empty(self):
        self.assertEqual(settings.normalize_base_url(""), DEFAULT_BASE_URL)
        self.assertEqual(settings.normalize_base_url("   "), DEFAULT_BASE_URL)
        self.assertEqual(settings.normalize_base_url(None), DEFAULT_BASE_URL)

    def test_https_kept_without_trailing_slash(self):
        self.assertEqual(
            settings.normalize_base_url(" https://converter.studio/api/ "), "https://converter.studio/api"
        )
        self.assertEqual(
            settings.normalize_base_url("https://Example.COM:8443/x/api"), "https://example.com:8443/x/api"
        )

    def test_plain_http_only_on_this_computer(self):
        self.assertEqual(
            settings.normalize_base_url("http://localhost:8080/api"), "http://localhost:8080/api"
        )
        self.assertEqual(
            settings.normalize_base_url("http://127.0.0.1:8080/api"), "http://127.0.0.1:8080/api"
        )
        self.assertEqual(settings.normalize_base_url("http://[::1]:8080/api"), "http://[::1]:8080/api")
        with self.assertRaises(SettingError) as raised:
            settings.normalize_base_url("http://converter.studio/api")
        self.assertEqual(raised.exception.code, "httpsOnly")

    def test_refuses_what_is_not_an_api_address(self):
        for value in (
            "ftp://converter.studio/api",
            "converter.studio/api",
            "https://user:secret@converter.studio/api",
            "https://converter.studio/api?x=1",
            "https://converter.studio/api#top",
            "https://converter.studio:99999/api",
            "https:///api",
        ):
            with self.assertRaises(SettingError, msg=value) as raised:
                settings.normalize_base_url(value)
            self.assertEqual(raised.exception.code, "badBaseUrl", value)


class KeyTest(unittest.TestCase):
    def test_trimmed(self):
        self.assertEqual(settings.normalize_key("  cvs_live_abc123  "), "cvs_live_abc123")
        self.assertEqual(settings.normalize_key(""), "")
        self.assertEqual(settings.normalize_key(None), "")

    def test_refuses_spaces_and_control_characters(self):
        for value in ("cvs_live_a b", "cvs_live_a\tb", "cvs_live_ä", "x" * 257, "cvs\x00live"):
            with self.assertRaises(SettingError, msg=repr(value)) as raised:
                settings.normalize_key(value)
            self.assertEqual(raised.exception.code, "badKey")


class OtherSettingsTest(unittest.TestCase):
    def test_max_credits(self):
        self.assertEqual(settings.normalize_max_credits(20), 20)
        self.assertEqual(settings.normalize_max_credits(7.6), 8)
        self.assertEqual(settings.normalize_max_credits(-3), 0)
        self.assertEqual(settings.normalize_max_credits(10**9), settings.MAX_CREDITS_LIMIT)
        self.assertEqual(settings.normalize_max_credits("nonsense"), settings.DEFAULT_MAX_CREDITS)
        self.assertEqual(settings.normalize_max_credits(None), settings.DEFAULT_MAX_CREDITS)

    def test_language_and_output(self):
        self.assertEqual(settings.normalize_language("tr"), "tr")
        self.assertEqual(settings.normalize_language("klingon"), "auto")
        self.assertEqual(settings.normalize_output("text"), "text")
        self.assertEqual(settings.normalize_output("pdf"), "document")

    def test_normalize_fills_defaults(self):
        self.assertEqual(settings.normalize({}), settings.DEFAULTS)
        values = settings.normalize({"MaxCredits": 5, "OcrLanguage": "de", "BaseUrl": None})
        self.assertEqual(values["MaxCredits"], 5)
        self.assertEqual(values["OcrLanguage"], "de")
        self.assertEqual(values["BaseUrl"], DEFAULT_BASE_URL)

    def test_site_of(self):
        self.assertEqual(settings.site_of("https://converter.studio/api"), "https://converter.studio")
        self.assertEqual(settings.site_of("http://localhost:8080"), "http://localhost:8080")

    def test_languages_match_the_api(self):
        # The API's OCR languages (packages/shared/src/behaviour.ts), "auto" first.
        self.assertEqual(settings.OCR_LANGUAGES[0], "auto")
        self.assertEqual(len(settings.OCR_LANGUAGES), 20)
        self.assertEqual(len(set(settings.OCR_LANGUAGES)), 20)


if __name__ == "__main__":
    unittest.main()
