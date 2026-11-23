# Converter Studio for LibreOffice

A LibreOffice extension that brings in the files LibreOffice cannot open, through
[Converter Studio](https://converter.studio):

- **Insert pictures** from an iPhone (HEIC, HEIF), AVIF pictures and camera RAW photos (CR2, NEF,
  ARW, DNG) into Writer, Calc, Impress and Draw.
- **Text from a scan (OCR):** the text of a scanned PDF or a photo of a page, in 19 languages, as a
  new document with paragraphs and tables, or as plain text at the cursor in Writer.
- **Open e-books** (EPUB, MOBI, AZW3) as Writer documents.

LibreOffice 24.2 and 26.8 read HEIC, AVIF and RAW files as text, have no text recognition, and do
not open EPUB, MOBI or AZW3 books. Everything else LibreOffice does itself (it opens WebP, TIFF,
FB2 and Markdown, and writes PDF, PDF/A, DOCX and EPUB), so the extension does not touch it.

![Writer with an iPhone photo inserted through the Converter Studio menu](listing/screenshot-2-heic-inserted.png)

## Requirements

- LibreOffice 24.2 or later, on Windows, macOS or Linux. Nothing else to install: the extension is
  written in Python and uses only what LibreOffice brings. On Linux distributions that split
  LibreOffice into packages, the Python bridge must be installed (Debian, Ubuntu: `python3-uno`;
  Fedora, openSUSE: `libreoffice-pyuno`).
- A Converter Studio account and an API key: sign up at [converter.studio](https://converter.studio),
  then create a key on the [account page](https://converter.studio/account#api-keys). Free accounts
  get credits every day.
- An internet connection: the files are converted on converter.studio.

## Install

- From LibreOffice: **Tools ▸ Extensions ▸ Get more extensions online**, search for "Converter
  Studio", or download it from the
  [LibreOffice Extensions site](https://extensions.libreoffice.org).
- Or download `converter-studio-<version>.oxt` from the
  [releases](https://github.com/tariksucu/libreoffice-converter-studio/releases), then **Tools ▸
  Extensions ▸ Add** and choose the file.

Accept the licence and restart LibreOffice. A **Converter Studio** menu appears in Writer, Calc,
Impress and Draw. LibreOffice offers new versions itself (**Tools ▸ Extensions ▸ Check for
Updates**).

## Set up

Open **Converter Studio ▸ Settings**:

- **API key:** paste your key (`cvs_live_…`); **Check** shows the account, its plan and its credits.
- **Remember the key:** the key is kept with LibreOffice's passwords for web connections (the store
  LibreOffice uses for WebDAV and FTP passwords), not in a settings file. On disk it is encrypted,
  with your master password if you set one, otherwise with LibreOffice's built-in one (Tools ▸
  Options ▸ LibreOffice ▸ Security ▸ Passwords for Web Connections, where you can also see or
  delete it). If LibreOffice is set not to save these passwords, the extension asks before turning
  that on; LibreOffice may then ask you for a master password. Without "Remember", or if you say
  no, the key is kept only until LibreOffice closes.
- **Ask before a file costs more than … credits** (20 by default; 0 asks every time). A file that
  costs more is not converted, and not charged, until you say yes.
- **Text recognition:** the language it starts with.
- **API address:** `https://converter.studio/api`. Change it only to try a test server.

## Use

- **Converter Studio ▸ Insert Picture (HEIC, AVIF, RAW)…** Choose a picture; it is converted (photos
  to JPG, AVIF to PNG, keeping transparency) and embedded in the document. In Writer it goes in at
  the cursor, in the line like a character, and the cursor moves after it, so several pictures
  follow one another; you can change its anchor and wrap as usual. In Calc it goes in at the current
  cell, in Impress and Draw on the current slide or page, as Insert ▸ Image does. The camera's
  details and location are not kept.
- **Converter Studio ▸ Text from a Scan (OCR)…** (Writer) Choose a scanned PDF or a picture (JPG,
  PNG, WebP, HEIC, TIFF, BMP), the language of the text (or let it detect it), and the result: a
  new, untitled document with paragraphs and tables, or plain text at the cursor.
- **Converter Studio ▸ Open an E-book (EPUB, MOBI, AZW3)…** (Writer) The book opens as a new,
  untitled document. Books with copy protection (DRM) cannot be converted.

A progress window shows the upload, the conversion and the download. **Cancel** stops waiting; a
conversion that has already started on converter.studio still finishes there and counts its
credits. Errors show Converter Studio's own explanation (for example "This API key does not work").

## Credits

A picture costs 1 credit, the text of a photo 2, the text of a scanned PDF 1 for every started 10
pages (up to 50 pages), and an e-book 1; very large files cost a little more. See
[pricing](https://converter.studio/pricing). The largest file depends on your plan.

## Privacy

The extension sends the file you choose (its contents, name and size) to converter.studio, and
nothing else about you or your documents: no document you have open, no usage statistics. It sends
only when you choose a command. converter.studio deletes the upload once it is converted and the
result after six hours; the extension downloads the result at once and deletes its own temporary
copy after using it. See the [privacy policy](https://converter.studio/privacy).

Connections use HTTPS with the certificate checked, through the system's proxy settings (the
`HTTPS_PROXY` variable, and on Windows and macOS the system's settings); LibreOffice's own proxy
settings are not read. LibreOffice's own builds bring a Python that does not always find the
system's certificate authorities; the extension then adds the system's bundle. It never turns
certificate checks off.

## From a macro

The same work, without dialogs, from a Basic or Python macro: the service
`studio.converter.libreoffice.Commands` takes named values and returns named values.

```basic
Sub InsertIphonePhoto
    Dim service As Object, result As Variant, item As Variant
    Dim args(2) As New com.sun.star.beans.NamedValue
    service = CreateUnoService("studio.converter.libreoffice.Commands")
    args(0).Name = "Command" : args(0).Value = "insertPicture"
    args(1).Name = "File" : args(1).Value = "/home/me/Pictures/IMG_2048.HEIC"
    args(2).Name = "Document" : args(2).Value = ThisComponent
    result = service.execute(args())
    For Each item In result
        Print item.Name & ": " & item.Value
    Next
End Sub
```

| `Command`       | Arguments                                                                                                      | Result                                                        |
| --------------- | -------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------- |
| `insertPicture` | `File`, `Document` (default: the current one), `MaxCredits`, `Confirm`                                         | the picture in the document                                   |
| `recognizeText` | `File`, `Language` (`auto`, `en`, `tr`…), `Output` (`document` or `text`), `Document`, `MaxCredits`, `Confirm` | `Document`: the new document, or the text at the cursor       |
| `openEbook`     | `File`, `MaxCredits`, `Confirm`                                                                                | `Document`: the new document                                  |
| `account`       |                                                                                                                | `Plan`, `CreditsLeft`                                         |
| `configure`     | `ApiKey`, `Remember`, `BaseUrl`, `MaxCredits`, `OcrLanguage`, `OcrOutput`                                      | `Key`: `saved`, `session` or `removed` (an empty key removes) |

Every result has `Status` (`done`, `failed` or `canceled`) and, unless done, `Code` and `Message`.
A file that costs more than `MaxCredits` is not converted unless `Confirm` is true. A macro never
turns on LibreOffice's saving of passwords: with saving off, `configure` keeps the key for the
session.

## Development

```sh
python3 -m unittest discover -s tests -t .   # the logic, with a fake API; no network
python3 tools/build.py                       # dist/converter-studio-<version>.oxt
python3 tools/smoke.py dist/converter-studio-<version>.oxt   # installs it into a throwaway profile
```

`extension/` is the package as LibreOffice reads it: `description.xml`, the menu (`Addons.xcu`),
the settings schema (`Settings.xcs`), the UNO component (`converter_studio.py`) and its modules
(`pythonpath/converterstudio`: the API client, the conversion flow and the texts need only Python's
standard library; `office.py` holds everything that talks to LibreOffice). Texts are in
`pythonpath/converterstudio/l10n/<language>.properties` and the menu titles in `Addons.xcu`;
English and Turkish are included, and a new language is a new `.properties` file.

## Licence

MIT, see [LICENSE](LICENSE). Converter Studio is a service of [converter.studio](https://converter.studio);
its terms apply to the conversions.
