import unittest

from converterstudio import formats
from converterstudio.formats import Unsupported


class RequestsTest(unittest.TestCase):
    def test_pictures_libreoffice_cannot_open(self):
        self.assertEqual(formats.picture_request("IMG_2048.HEIC"), ("jpg", {}))
        self.assertEqual(formats.picture_request("photo.heif"), ("jpg", {}))
        self.assertEqual(formats.picture_request("logo.avif"), ("png", {}))
        for raw in ("a.CR2", "a.nef", "a.ARW", "a.dng"):
            self.assertEqual(formats.picture_request(raw)[0], "jpg", raw)

    def test_pictures_libreoffice_opens_itself_are_refused(self):
        for name in ("a.png", "a.jpg", "a.webp", "a.svg", "noextension", ""):
            with self.assertRaises(Unsupported, msg=name):
                formats.picture_request(name)

    def test_text_recognition(self):
        self.assertEqual(
            formats.ocr_request("scan.pdf", "de", "document"), ("docx", {"ocrLanguage": "de", "ocr": True})
        )
        self.assertEqual(
            formats.ocr_request("SCAN.PDF", "auto", "text"), ("txt", {"ocrLanguage": "auto", "ocr": True})
        )
        self.assertEqual(formats.ocr_request("page.jpeg", "en", "text"), ("txt", {"ocrLanguage": "en"}))
        self.assertEqual(formats.ocr_request("page.tif", "", "document"), ("docx", {"ocrLanguage": "auto"}))
        with self.assertRaises(Unsupported):
            formats.ocr_request("notes.docx")

    def test_ebooks(self):
        for name in ("book.epub", "book.MOBI", "book.azw3"):
            self.assertEqual(formats.ebook_request(name), ("docx", {}))
        for name in ("book.fb2", "book.pdf"):
            with self.assertRaises(Unsupported, msg=name):
                formats.ebook_request(name)

    def test_every_filter_names_only_what_its_command_takes(self):
        for _key, extensions in formats.PICTURE_FILTERS:
            for ext in extensions:
                formats.picture_request("x." + ext)
        for _key, extensions in formats.OCR_FILTERS:
            for ext in extensions:
                formats.ocr_request("x." + ext)
        for _key, extensions in formats.EBOOK_FILTERS:
            for ext in extensions:
                formats.ebook_request("x." + ext)


class HelpersTest(unittest.TestCase):
    def test_extension(self):
        self.assertEqual(formats.extension("/a/b/Photo.HEIC"), "heic")
        self.assertEqual(formats.extension("archive.tar.gz"), "gz")
        self.assertEqual(formats.extension("README"), "")
        self.assertEqual(formats.extension(None), "")

    def test_patterns_in_both_cases(self):
        self.assertEqual(formats.patterns(("heic", "avif")), "*.heic;*.HEIC;*.avif;*.AVIF")

    def test_safe_file_name(self):
        self.assertEqual(formats.safe_file_name("photo.jpg", "x.jpg"), "photo.jpg")
        self.assertEqual(formats.safe_file_name("../../etc/passwd", "x.txt"), "passwd")
        self.assertEqual(formats.safe_file_name("..\\..\\evil.docx", "x.docx"), "evil.docx")
        self.assertEqual(formats.safe_file_name('a<b>:"c|?*.txt', "x.txt"), "abc.txt")
        self.assertEqual(formats.safe_file_name("bad\x00\x07name.txt", "x.txt"), "badname.txt")
        self.assertEqual(formats.safe_file_name("", "result.docx"), "result.docx")
        self.assertEqual(formats.safe_file_name(None, "result.docx"), "result.docx")
        self.assertEqual(formats.safe_file_name("..", "result.docx"), "result.docx")
        long_name = formats.safe_file_name("a" * 300 + ".jpg", "x.jpg")
        self.assertTrue(long_name.endswith(".jpg"))
        self.assertLessEqual(len(long_name), 120)

    def test_fit_keeps_proportions_and_never_enlarges(self):
        self.assertEqual(formats.fit((42333, 28231), (17000, 24700)), (17000, 11336))
        self.assertEqual(formats.fit((5000, 3000), (17000, 24700)), (5000, 3000))
        self.assertEqual(formats.fit((10000, 50000), (17000, 24700)), (4940, 24700))
        self.assertEqual(formats.fit((0, 0), (17000, 24700)), (1, 1))


if __name__ == "__main__":
    unittest.main()
