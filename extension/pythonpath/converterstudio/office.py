"""Everything that talks to LibreOffice: settings, the saved key, dialogs, and putting results
into documents. Imported only inside LibreOffice (it needs `uno`)."""

import os
import shutil
import tempfile
import threading
import time

import uno
import unohelper
from com.sun.star.awt import XActionListener
from com.sun.star.beans import NamedValue, PropertyValue

from . import KEYS_PAGE, PRIVACY_PAGE, VERSION, api, formats, job, settings, tls
from .messages import Catalog, credit_count, error_text, human_size

EXTENSION_ID = "studio.converter.libreoffice"
SETTINGS_PATH = "/studio.converter.libreoffice.Settings/General"
# The key is kept in LibreOffice's password container under the API's address and this name.
KEY_USER = "api-key"

TEXT_DOCUMENT = "com.sun.star.text.TextDocument"

# Only one conversion at a time: its dialog is modal, but another window could start a second.
_busy = threading.Lock()


SELECTED_OBJECTS = (
    "com.sun.star.text.TextGraphicObject",
    "com.sun.star.text.TextFrame",
    "com.sun.star.text.TextEmbeddedObject",
    "com.sun.star.drawing.ShapeCollection",
    "com.sun.star.drawing.Shapes",
)


def _picture_selected(document):
    """Whether a picture, frame or shape is selected (rather than text or cells)."""
    try:
        selection = document.getCurrentController().getSelection()
    except Exception:
        return False
    if selection is None or not hasattr(selection, "supportsService"):
        return False
    return any(selection.supportsService(name) for name in SELECTED_OBJECTS)


def picture_size(graphic):
    """A picture's size in 1/100 mm: its own, or its pixels at 96 dpi when it gives none."""
    size = graphic.getPropertyValue("Size100thMM")
    if size.Width > 0 and size.Height > 0:
        return size.Width, size.Height
    pixels = graphic.getPropertyValue("SizePixel")
    return pixels.Width * 2540 // 96, pixels.Height * 2540 // 96


def text_area(document, cursor):
    """The width and height (1/100 mm) a picture may take on the cursor's page, as Insert ▸
    Image allows: the page without its margins."""
    try:
        styles = document.getStyleFamilies().getByName("PageStyles")
        page = styles.getByName(cursor.getPropertyValue("PageStyleName"))
        return (
            page.Width - page.LeftMargin - page.RightMargin,
            page.Height - page.TopMargin - page.BottomMargin,
        )
    except Exception:
        return 17000, 24700  # A4 with 2 cm margins


def _props(**values):
    return tuple(PropertyValue(Name=k, Value=v) for k, v in values.items())


def _const(name):
    return uno.getConstantByName(name)


class Office:
    """The running LibreOffice, as the commands need it."""

    def __init__(self, ctx):
        self.ctx = ctx
        self.smgr = ctx.ServiceManager

    def create(self, name, *args):
        if args:
            return self.smgr.createInstanceWithArgumentsAndContext(name, args, self.ctx)
        return self.smgr.createInstanceWithContext(name, self.ctx)

    # -- configuration --------------------------------------------------------------------

    def _config(self, path, update=False):
        provider = self.create("com.sun.star.configuration.ConfigurationProvider")
        service = (
            "com.sun.star.configuration.ConfigurationUpdateAccess"
            if update
            else "com.sun.star.configuration.ConfigurationAccess"
        )
        return provider.createInstanceWithArguments(service, (NamedValue("nodepath", path),))

    def read_settings(self):
        values = {}
        try:
            node = self._config(SETTINGS_PATH)
            for name in settings.DEFAULTS:
                if node.hasByName(name):
                    values[name] = node.getByName(name)
        except Exception:
            pass
        try:
            return settings.normalize(values)
        except settings.SettingError:
            values.pop("BaseUrl", None)
            return settings.normalize(values)

    def write_settings(self, values):
        node = self._config(SETTINGS_PATH, update=True)
        for name, value in values.items():
            # A Python int small enough goes over UNO as a long, the type of MaxCredits.
            node.replaceByName(name, int(value) if name == "MaxCredits" else value)
        node.commitChanges()

    def ui_locale(self):
        for name in ("ooLocale", "ooSetupSystemLocale"):
            try:
                value = self._config("/org.openoffice.Setup/L10N").getByName(name)
            except Exception:
                value = ""
            if value:
                return value
        return "en-US"

    def version(self):
        try:
            node = self._config("/org.openoffice.Setup/Product")
            return node.getByName("ooSetupVersionAboutBox") or node.getByName("ooSetupVersion")
        except Exception:
            return ""

    # -- documents --------------------------------------------------------------------------

    def desktop(self):
        return self.create("com.sun.star.frame.Desktop")

    def current_document(self):
        try:
            return self.desktop().getCurrentComponent()
        except Exception:
            return None

    @staticmethod
    def frame_of(document):
        try:
            return document.getCurrentController().getFrame()
        except Exception:
            return None

    def window_of(self, document):
        frame = self.frame_of(document)
        return frame.getContainerWindow() if frame is not None else None

    def insert_picture(self, document, path):
        """Inserts a picture, embedded in the document: in Writer at the cursor, in the text like
        a character (the cursor goes after it, so several pictures follow one another); in Calc,
        Impress and Draw the way Insert ▸ Image does (at the current cell, on the current slide)."""
        frame = self.frame_of(document)
        if frame is None:
            raise RuntimeError("no window")
        helper = self.create("com.sun.star.frame.DispatchHelper")
        if _picture_selected(document):
            # A picture LibreOffice has just inserted stays selected, and Insert ▸ Image would
            # replace it: leave the selection first, as Esc does. Called from another thread than
            # LibreOffice's own (a macro over UNO), Esc is carried out a moment later: wait.
            helper.executeDispatch(frame, ".uno:Escape", "", 0, ())
            deadline = time.monotonic() + 3
            while _picture_selected(document) and time.monotonic() < deadline:
                time.sleep(0.05)
        if document.supportsService(TEXT_DOCUMENT):
            self._insert_into_text(document, path)
            return
        helper.executeDispatch(
            frame, ".uno:InsertGraphic", "", 0, _props(FileName=uno.systemPathToFileUrl(path), AsLink=False)
        )

    def _insert_into_text(self, document, path):
        graphic = self.create("com.sun.star.graphic.GraphicProvider").queryGraphic(
            _props(URL=uno.systemPathToFileUrl(path))
        )
        if graphic is None:
            raise RuntimeError("LibreOffice could not read the converted picture")
        cursor = document.getCurrentController().getViewCursor()
        width, height = formats.fit(picture_size(graphic), text_area(document, cursor))
        picture = document.createInstance("com.sun.star.text.TextGraphicObject")
        picture.Graphic = graphic
        picture.AnchorType = uno.Enum("com.sun.star.text.TextContentAnchorType", "AS_CHARACTER")
        picture.Width = width
        picture.Height = height
        cursor.getText().insertTextContent(cursor, picture, False)

    @staticmethod
    def insert_text(document, text):
        """Inserts plain text at the cursor of a text document, one paragraph per line."""
        cursor = document.getCurrentController().getViewCursor()
        target = cursor.getText()
        position = target.createTextCursorByRange(cursor.getEnd())
        lines = text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n").split("\n")
        paragraph = _const("com.sun.star.text.ControlCharacter.PARAGRAPH_BREAK")
        for index, line in enumerate(lines):
            if index:
                target.insertControlCharacter(position, paragraph, False)
            target.insertString(position, line, False)

    def open_as_new(self, path):
        """Opens a file as a new, untitled document (saving asks where to)."""
        return self.desktop().loadComponentFromURL(
            uno.systemPathToFileUrl(path), "_blank", 0, _props(AsTemplate=True)
        )

    # -- the user ----------------------------------------------------------------------------

    def message(self, parent, title, text, kind="info"):
        """A message box; for "query", True when the answer is Yes."""
        toolkit = self.create("com.sun.star.awt.Toolkit")
        box_type = {"info": "INFOBOX", "error": "ERRORBOX", "warning": "WARNINGBOX", "query": "QUERYBOX"}[
            kind
        ]
        buttons = _const(
            "com.sun.star.awt.MessageBoxButtons." + ("BUTTONS_YES_NO" if kind == "query" else "BUTTONS_OK")
        )
        peer = parent if parent is not None else toolkit.getDesktopWindow()
        box = toolkit.createMessageBox(
            peer, uno.Enum("com.sun.star.awt.MessageBoxType", box_type), buttons, title, text
        )
        try:
            result = box.execute()
        finally:
            box.dispose()
        return result == _const("com.sun.star.awt.MessageBoxResults.YES")

    def pick_file(self, title, filters, catalog):
        """The system path of a local file the user chooses, or None."""
        picker = self.create("com.sun.star.ui.dialogs.FilePicker")
        picker.initialize((_const("com.sun.star.ui.dialogs.TemplateDescription.FILEOPEN_SIMPLE"),))
        picker.setTitle(title)
        first = None
        for key, extensions in filters:
            label = catalog.get(key)
            picker.appendFilter(label, formats.patterns(extensions))
            first = first or label
        picker.appendFilter("*.*", "*.*")
        if first:
            picker.setCurrentFilter(first)
        if picker.execute() != 1:
            return None
        files = picker.getSelectedFiles() if hasattr(picker, "getSelectedFiles") else picker.getFiles()
        if not files:
            return None
        url = files[0]
        if not url.startswith("file:"):
            raise OSError("only local files")
        return uno.fileUrlToSystemPath(url)


class KeyStore:
    """The API key, kept in LibreOffice's password container (Tools ▸ Options ▸ LibreOffice ▸
    Security ▸ Passwords for Web Connections): encrypted on disk, with the user's master
    password if one is set, or only in memory until LibreOffice closes."""

    def __init__(self, office, parent=None):
        self.office = office
        self.container = office.create("com.sun.star.task.PasswordContainer")
        args = (NamedValue("Parent", parent),) if parent is not None else ()
        self.handler = office.create("com.sun.star.task.InteractionHandler", *args)

    def get(self, base_url):
        try:
            record = self.container.findForName(base_url, KEY_USER, self.handler)
        except Exception:
            return ""
        users = record.UserList if record else ()
        if users and users[0].Passwords:
            return users[0].Passwords[0]
        return ""

    def storing_allowed(self):
        try:
            return bool(self.container.isPersistentStoringAllowed())
        except Exception:
            return False

    def save(self, base_url, key, remember, allow_storing=None):
        """Keeps the key; returns "saved" (on disk) or "session" (until LibreOffice closes).

        When saving to disk is off in LibreOffice, `allow_storing()` is asked whether to turn it
        on; LibreOffice then asks for a master password itself, when there is none yet."""
        self.remove(base_url)
        if remember:
            turned_on = False
            if not self.storing_allowed() and allow_storing is not None and allow_storing():
                self.container.allowPersistentStoring(True)
                turned_on = True
            if self.storing_allowed():
                try:
                    self.container.addPersistent(base_url, KEY_USER, (key,), self.handler)
                    return "saved"
                except Exception:
                    if turned_on:
                        self.container.allowPersistentStoring(False)
        self.container.add(base_url, KEY_USER, (key,), self.handler)
        return "session"

    def remove(self, base_url):
        for method in ("removePersistent", "remove"):
            try:
                getattr(self.container, method)(base_url, KEY_USER)
            except Exception:
                pass


class _Listener(unohelper.Base, XActionListener):
    def __init__(self, callback):
        self.callback = callback

    def actionPerformed(self, event):
        self.callback()

    def disposing(self, event):
        pass


class Dialog:
    """A small dialog built in code (sizes in LibreOffice's font-relative units)."""

    def __init__(self, office, title, width, height):
        self.office = office
        self.model = office.create("com.sun.star.awt.UnoControlDialogModel")
        self.model.Title = title
        self.model.Width = width
        self.model.Height = height
        self.control = None
        self._listeners = []

    def add(self, kind, name, x, y, width, height, **props):
        model = self.model.createInstance("com.sun.star.awt.UnoControl%sModel" % kind)
        model.PositionX, model.PositionY, model.Width, model.Height = x, y, width, height
        for key, value in props.items():
            setattr(model, key, value)
        self.model.insertByName(name, model)
        return model

    def on_click(self, name, callback):
        self._listeners.append((name, _Listener(callback)))

    def open(self, parent=None):
        """Makes the window (hidden until `run`)."""
        self.control = self.office.create("com.sun.star.awt.UnoControlDialog")
        self.control.setModel(self.model)
        for name, listener in self._listeners:
            self.control.getControl(name).addActionListener(listener)
        self.control.createPeer(self.office.create("com.sun.star.awt.Toolkit"), parent)
        if parent is not None:
            # Over the document's window (a dialog built in code starts at the screen's corner).
            try:
                outer, own = parent.getPosSize(), self.control.getPosSize()
                x = outer.X + max(0, (outer.Width - own.Width) // 2)
                y = outer.Y + max(0, (outer.Height - own.Height) // 3)
                self.control.setPosSize(x, y, 0, 0, _const("com.sun.star.awt.PosSize.POS"))
            except Exception:
                pass

    def run(self):
        """Shows it until it is closed; True when closed with OK."""
        return self.control.execute() == 1

    def close(self):
        if self.control is not None:
            self.control.dispose()
            self.control = None

    def get(self, name):
        return self.model.getByName(name)


class Commands:
    """The menu commands (interactive) and the same work for macros (`scripted`)."""

    def __init__(self, ctx):
        self.office = Office(ctx)
        self.catalog = Catalog(self.office.ui_locale())
        self.t = self.catalog.get

    # -- shared ------------------------------------------------------------------------------

    def credit_question(self, name, credits, limit):
        return self.t(
            "confirmCredits",
            name=name,
            cost=credit_count(self.catalog, credits),
            limit=credit_count(self.catalog, limit),
        )

    def client(self, values, key):
        transport = api.urllib_transport(tls.make_context())
        return api.Client(values["BaseUrl"], key, transport, office_version=self.office.version())

    def convert(
        self, values, key, path, to, options, max_credits, progress=None, cancelled=None, confirm=None
    ):
        workdir = tempfile.mkdtemp(prefix="converterstudio-")
        try:
            result, view = job.run(
                self.client(values, key),
                path,
                to,
                options,
                max_credits,
                workdir,
                progress,
                cancelled,
                confirm,
            )
        except BaseException:
            shutil.rmtree(workdir, ignore_errors=True)
            raise
        return workdir, result, view

    # -- menu commands -----------------------------------------------------------------------

    def interactive(self, command):
        document = self.office.current_document()
        parent = self.office.window_of(document) if document is not None else None
        if command == "settings":
            self.settings_dialog(parent)
            return
        if not _busy.acquire(False):
            self.office.message(parent, self.t("title"), self.t("busy"), "warning")
            return
        try:
            if command == "insertPicture":
                self.insert_picture(document, parent)
            elif command == "recognizeText":
                self.recognize_text(document, parent)
            elif command == "openEbook":
                self.open_ebook(parent)
        finally:
            _busy.release()

    def _ready(self, parent):
        """The settings and the key, or None after telling the user to add one."""
        values = self.office.read_settings()
        key = KeyStore(self.office, parent).get(values["BaseUrl"])
        if not key:
            self.office.message(parent, self.t("title"), self.t("error.noKey"), "info")
            self.settings_dialog(parent)
            values = self.office.read_settings()
            key = KeyStore(self.office, parent).get(values["BaseUrl"])
        return (values, key) if key else None

    def _pick(self, parent, title_key, filters, check, unsupported_key):
        path = None
        try:
            path = self.office.pick_file(self.t(title_key), filters, self.catalog)
        except OSError as error:
            self.office.message(parent, self.t("title"), self.t("error.readFile", detail=str(error)), "error")
        if path is None:
            return None
        try:
            request = check(os.path.basename(path))
        except formats.Unsupported:
            self.office.message(parent, self.t("title"), self.t(unsupported_key), "info")
            return None
        return path, request

    def insert_picture(self, document, parent):
        ready = self._ready(parent)
        if not ready:
            return
        values, key = ready
        picked = self._pick(
            parent, "pickPicture", formats.PICTURE_FILTERS, formats.picture_request, "unsupportedPicture"
        )
        if not picked:
            return
        path, (to, options) = picked
        outcome = self.with_progress(parent, values, key, path, to, options)
        if outcome is None:
            return
        workdir, result = outcome
        try:
            self.office.insert_picture(document, result)
        except Exception as error:
            self.office.message(parent, self.t("title"), self.t("error.insert", detail=str(error)), "error")
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    def recognize_text(self, document, parent):
        ready = self._ready(parent)
        if not ready:
            return
        values, key = ready
        picked = self._pick(parent, "pickScan", formats.OCR_FILTERS, formats.ocr_request, "unsupportedScan")
        if not picked:
            return
        path = picked[0]
        choice = self.ocr_dialog(parent, os.path.basename(path), values)
        if choice is None:
            return
        language, output = choice
        values = dict(values, OcrLanguage=language, OcrOutput=output)
        try:
            self.office.write_settings({"OcrLanguage": language, "OcrOutput": output})
        except Exception:
            pass
        writer = document is not None and document.supportsService(TEXT_DOCUMENT)
        if output == "text" and not writer:
            self.office.message(parent, self.t("title"), self.t("ocrTextNeedsWriter"), "info")
            output = "document"
        to, options = formats.ocr_request(path, language, output)
        outcome = self.with_progress(parent, values, key, path, to, options)
        if outcome is None:
            return
        workdir, result = outcome
        try:
            if to == "txt":
                with open(result, encoding="utf-8", errors="replace") as handle:
                    self.office.insert_text(document, handle.read())
            else:
                self.office.open_as_new(result)
        except Exception as error:
            self.office.message(parent, self.t("title"), self.t("error.insert", detail=str(error)), "error")
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    def open_ebook(self, parent):
        ready = self._ready(parent)
        if not ready:
            return
        values, key = ready
        picked = self._pick(
            parent, "pickEbook", formats.EBOOK_FILTERS, formats.ebook_request, "unsupportedEbook"
        )
        if not picked:
            return
        path, (to, options) = picked
        outcome = self.with_progress(parent, values, key, path, to, options)
        if outcome is None:
            return
        workdir, result = outcome
        try:
            self.office.open_as_new(result)
        except Exception as error:
            self.office.message(parent, self.t("title"), self.t("error.insert", detail=str(error)), "error")
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    # -- dialogs -----------------------------------------------------------------------------

    def ocr_dialog(self, parent, name, values):
        """(language, output) for a text recognition, or None."""
        dialog = Dialog(self.office, self.t("ocrTitle"), 290, 112)
        dialog.add("FixedText", "file", 8, 8, 274, 10, Label=self.t("ocrFile", name=name))
        dialog.add("FixedText", "languageLabel", 8, 26, 80, 10, Label=self.t("ocrLanguage"))
        labels = [self.t("lang." + code) for code in settings.OCR_LANGUAGES]
        current = settings.OCR_LANGUAGES.index(values["OcrLanguage"])
        dialog.add(
            "ListBox",
            "language",
            90,
            24,
            140,
            13,
            Dropdown=True,
            StringItemList=tuple(labels),
            SelectedItems=(current,),
            LineCount=12,
        )
        dialog.add("FixedText", "outputLabel", 8, 46, 80, 10, Label=self.t("ocrOutput"))
        as_text = values["OcrOutput"] == "text"
        dialog.add(
            "RadioButton",
            "asDocument",
            90,
            45,
            192,
            10,
            Label=self.t("ocrOutputDocument"),
            State=0 if as_text else 1,
        )
        dialog.add(
            "RadioButton", "asText", 90, 58, 192, 10, Label=self.t("ocrOutputText"), State=1 if as_text else 0
        )
        dialog.add("FixedLine", "line", 8, 74, 274, 6)
        dialog.add("Button", "ok", 178, 90, 50, 14, Label=self.t("ok"), PushButtonType=1, DefaultButton=True)
        dialog.add("Button", "cancel", 232, 90, 50, 14, Label=self.t("cancel"), PushButtonType=2)
        dialog.open(parent)
        try:
            if not dialog.run():
                return None
            selected = dialog.get("language").SelectedItems
            language = settings.OCR_LANGUAGES[selected[0]] if selected else "auto"
            output = "text" if dialog.get("asText").State == 1 else "document"
        finally:
            dialog.close()
        return language, output

    def settings_dialog(self, parent):
        """The settings; True when saved."""
        values = self.office.read_settings()
        store = KeyStore(self.office, parent)
        form = {
            "key": store.get(values["BaseUrl"]),
            "remember": 1,
            "maxCredits": values["MaxCredits"],
            "language": values["OcrLanguage"],
            "baseUrl": values["BaseUrl"],
        }
        while True:
            saved = self._settings_form(parent, store, values, form)
            if saved is None:
                return False
            try:
                base = settings.normalize_base_url(form["baseUrl"])
                typed = settings.normalize_key(form["key"])
            except settings.SettingError as error:
                self.office.message(parent, self.t("title"), self.t("error." + error.code), "error")
                continue
            break
        self.office.write_settings(
            {
                "BaseUrl": base,
                "MaxCredits": settings.normalize_max_credits(form["maxCredits"]),
                "OcrLanguage": settings.normalize_language(form["language"]),
            }
        )
        if base != values["BaseUrl"]:
            store.remove(values["BaseUrl"])
        if typed:
            remember = form["remember"] == 1
            where = store.save(
                base,
                typed,
                remember,
                lambda: self.office.message(
                    parent, self.t("title"), self.t("enableStorageQuestion"), "query"
                ),
            )
            if remember and where != "saved":
                self.office.message(parent, self.t("title"), self.t("storageFailed"), "warning")
        else:
            store.remove(base)
        return True

    def _settings_form(self, parent, store, values, form):
        """Shows the settings form filled from `form` and copies what was typed back into it;
        None when cancelled."""
        dialog = Dialog(self.office, self.t("settingsTitle"), 290, 234)
        dialog.add("FixedText", "keyLabel", 8, 10, 76, 10, Label=self.t("apiKey"))
        dialog.add("Edit", "key", 86, 8, 140, 13, Text=form["key"], EchoChar=0x2022)
        dialog.add("FixedHyperlink", "getKey", 232, 10, 52, 10, Label=self.t("getKey"), URL=KEYS_PAGE)
        dialog.add(
            "CheckBox", "remember", 86, 25, 196, 10, Label=self.t("rememberKey"), State=form["remember"]
        )
        dialog.add("FixedText", "where", 86, 37, 196, 40, Label=self.t("keyWhereSaved"), MultiLine=True)
        dialog.add("FixedText", "creditsLabel", 8, 82, 150, 10, Label=self.t("maxCredits"))
        dialog.add(
            "NumericField",
            "maxCredits",
            160,
            80,
            40,
            13,
            Value=float(form["maxCredits"]),
            ValueMin=0.0,
            ValueMax=float(settings.MAX_CREDITS_LIMIT),
            DecimalAccuracy=0,
            Spin=True,
            StrictFormat=True,
        )
        dialog.add("FixedText", "creditsUnit", 204, 82, 78, 10, Label=self.t("credits"))
        dialog.add("FixedText", "languageLabel", 8, 100, 76, 10, Label=self.t("ocrDefaultLanguage"))
        labels = tuple(self.t("lang." + code) for code in settings.OCR_LANGUAGES)
        current = settings.OCR_LANGUAGES.index(settings.normalize_language(form["language"]))
        dialog.add(
            "ListBox",
            "language",
            86,
            98,
            140,
            13,
            Dropdown=True,
            StringItemList=labels,
            SelectedItems=(current,),
            LineCount=12,
        )
        dialog.add("FixedText", "urlLabel", 8, 118, 76, 10, Label=self.t("baseUrl"))
        dialog.add("Edit", "baseUrl", 86, 116, 196, 13, Text=form["baseUrl"])
        dialog.add("Button", "check", 86, 134, 60, 14, Label=self.t("checkKey"))
        dialog.add("FixedText", "status", 150, 132, 132, 32, Label="", MultiLine=True)
        dialog.add("FixedText", "privacy", 8, 170, 274, 20, Label=self.t("privacyNote"), MultiLine=True)
        dialog.add(
            "FixedHyperlink", "privacyLink", 8, 192, 100, 10, Label=self.t("privacyLink"), URL=PRIVACY_PAGE
        )
        dialog.add("FixedLine", "line", 8, 202, 274, 6)
        dialog.add("FixedText", "version", 8, 216, 120, 10, Label=self.t("version", version=VERSION))
        dialog.add("Button", "remove", 130, 212, 60, 14, Label=self.t("removeKey"))
        dialog.add(
            "Button", "save", 194, 212, 44, 14, Label=self.t("save"), PushButtonType=1, DefaultButton=True
        )
        dialog.add("Button", "cancel", 242, 212, 40, 14, Label=self.t("cancel"), PushButtonType=2)

        def status(text):
            dialog.get("status").Label = text

        def check():
            try:
                base = settings.normalize_base_url(dialog.get("baseUrl").Text)
                typed = settings.normalize_key(dialog.get("key").Text)
            except settings.SettingError as error:
                status(self.t("error." + error.code))
                return
            if not typed:
                status(self.t("error.noKey"))
                return
            status("…")
            try:
                account = self.client(dict(values, BaseUrl=base), typed).account()
            except api.ApiError as error:
                status(error_text(self.catalog, error))
                return
            status(
                self.t(
                    "accountOk",
                    email=account.get("email", ""),
                    plan=account.get("plan", ""),
                    credits=account.get("credits", ""),
                )
            )

        def remove():
            try:
                base = settings.normalize_base_url(dialog.get("baseUrl").Text)
            except settings.SettingError:
                base = values["BaseUrl"]
            store.remove(base)
            dialog.get("key").Text = ""
            status(self.t("keyRemoved"))

        dialog.on_click("check", check)
        dialog.on_click("remove", remove)
        dialog.open(parent)
        try:
            if not dialog.run():
                return None
            selected = dialog.get("language").SelectedItems
            form.update(
                key=dialog.get("key").Text,
                remember=dialog.get("remember").State,
                maxCredits=dialog.get("maxCredits").Value,
                language=settings.OCR_LANGUAGES[selected[0]] if selected else "auto",
                baseUrl=dialog.get("baseUrl").Text,
            )
        finally:
            dialog.close()
        return form

    # -- progress ----------------------------------------------------------------------------

    def with_progress(self, parent, values, key, path, to, options):
        """Converts with a progress dialog; (workdir, result) or None (stopped or failed, the user
        has been told)."""
        name = os.path.basename(path)
        dialog = Dialog(self.office, self.t("title"), 220, 62)
        dialog.add("FixedText", "label", 8, 8, 204, 10, Label=self.t("progressWaiting"))
        dialog.add(
            "ProgressBar", "bar", 8, 22, 204, 10, ProgressValueMin=0, ProgressValueMax=1000, ProgressValue=0
        )
        dialog.add("Button", "cancel", 162, 40, 50, 14, Label=self.t("cancel"), PushButtonType=2)

        state = {
            "done": False,
            "question": None,
            "answer": False,
            "seen": False,
            "outcome": None,
            "error": None,
        }
        stop = threading.Event()
        answered = threading.Event()

        def update(step, done, total):
            if step == job.Steps.UPLOAD:
                text = self.t("progressUpload", name=name, done=human_size(done), total=human_size(total))
                fraction = 0.45 * (done / float(total or 1))
            elif step == job.Steps.CONVERT:
                text = self.t("progressConvert", name=name, percent=int(done or 0))
                fraction = 0.45 + 0.45 * (min(100, done or 0) / 100.0)
            else:
                text = self.t("progressDownload")
                fraction = 0.9 + 0.1 * (done / float(total or 1) if total else 0)
            try:
                dialog.get("label").Label = text
                dialog.get("bar").ProgressValue = int(1000 * min(1.0, fraction))
            except Exception:
                pass

        def poke():
            """Closes the running dialog until the main thread has seen why (it may not be
            running yet)."""
            while not state["seen"] and not stop.is_set():
                try:
                    if dialog.control is not None:
                        dialog.control.endExecute()
                except Exception:
                    pass
                time.sleep(0.1)

        def confirm(credits):
            state["seen"] = False
            answered.clear()
            state["question"] = credits
            poke()
            answered.wait()
            return state["answer"] and not stop.is_set()

        def work():
            try:
                outcome = self.convert(
                    values, key, path, to, options, values["MaxCredits"], update, stop.is_set, confirm
                )
                if stop.is_set():
                    # Finished after the user had stopped waiting: nobody takes the result.
                    shutil.rmtree(outcome[0], ignore_errors=True)
                else:
                    state["outcome"] = outcome
            except BaseException as error:
                state["error"] = error
            finally:
                state["seen"] = False
                state["done"] = True
                poke()

        thread = threading.Thread(target=work, name="converterstudio", daemon=True)
        dialog.open(parent)
        thread.start()
        try:
            while True:
                if state["done"]:
                    state["seen"] = True
                    break
                if state["question"] is not None:
                    credits, state["question"] = state["question"], None
                    state["seen"] = True
                    state["answer"] = self.office.message(
                        parent,
                        self.t("title"),
                        self.credit_question(name, credits, values["MaxCredits"]),
                        "query",
                    )
                    answered.set()
                    continue
                dialog.run()
                if state["done"] or state["question"] is not None:
                    continue
                # Closed by the user: stop.
                stop.set()
                answered.set()
                state["seen"] = True
                break
        finally:
            dialog.close()

        if stop.is_set() and not state["done"]:
            self.office.message(parent, self.t("title"), self.t("canceledNote"), "info")
            return None
        error = state["error"]
        if isinstance(error, api.Canceled):
            return None
        if isinstance(error, api.ApiError):
            self.office.message(parent, self.t("title"), error_text(self.catalog, error), "error")
            return None
        if isinstance(error, OSError):
            self.office.message(parent, self.t("title"), self.t("error.readFile", detail=str(error)), "error")
            return None
        if error is not None:
            self.office.message(
                parent, self.t("title"), self.t("error.other", code=type(error).__name__), "error"
            )
            return None
        workdir, result, _view = state["outcome"]
        return workdir, result

    # -- macros ------------------------------------------------------------------------------

    def scripted(self, arguments):
        """The commands without dialogs, for macros: see README "From a macro"."""
        args = {item.Name: item.Value for item in arguments}
        command = args.get("Command", "")
        if command == "configure":
            return self._configure(args)
        values = self.office.read_settings()
        document = args.get("Document") or self.office.current_document()
        store = KeyStore(self.office, self.office.window_of(document) if document is not None else None)
        key = store.get(values["BaseUrl"])
        if command == "account":
            try:
                account = self.client(values, key).account()
            except api.ApiError as error:
                return _result("failed", error=error, catalog=self.catalog)
            return _result(
                "done", Plan=str(account.get("plan", "")), CreditsLeft=int(account.get("credits") or 0)
            )
        path = args.get("File", "")
        if isinstance(path, str) and path.startswith("file:"):
            path = uno.fileUrlToSystemPath(path)
        name = os.path.basename(path or "")
        try:
            if command == "insertPicture":
                to, options = formats.picture_request(name)
            elif command == "recognizeText":
                output = settings.normalize_output(args.get("Output", values["OcrOutput"]))
                language = settings.normalize_language(args.get("Language", values["OcrLanguage"]))
                if output == "text" and not (
                    document is not None and document.supportsService(TEXT_DOCUMENT)
                ):
                    output = "document"
                to, options = formats.ocr_request(name, language, output)
            elif command == "openEbook":
                to, options = formats.ebook_request(name)
            else:
                raise formats.Unsupported(command)
        except formats.Unsupported:
            return _result(
                "failed",
                Code="unsupported",
                Message=self.t(
                    "unsupportedPicture"
                    if command == "insertPicture"
                    else "unsupportedScan"
                    if command == "recognizeText"
                    else "unsupportedEbook"
                ),
            )
        if not os.path.isfile(path):
            return _result("failed", Code="readFile", Message=self.t("error.readFile", detail=path))
        max_credits = settings.normalize_max_credits(args.get("MaxCredits", values["MaxCredits"]))
        go_ahead = bool(args.get("Confirm", False))
        asked = {}

        def confirm(credits):
            asked["credits"] = credits
            return go_ahead

        try:
            workdir, result, view = self.convert(values, key, path, to, options, max_credits, confirm=confirm)
        except api.Canceled:
            return _result(
                "canceled",
                Code="aboveMaxCredits",
                Credits=int(asked.get("credits") or 0),
                Message=self.credit_question(name, asked.get("credits"), max_credits),
            )
        except api.ApiError as error:
            return _result("failed", error=error, catalog=self.catalog)
        extra = {}
        try:
            if command == "insertPicture":
                self.office.insert_picture(document, result)
            elif to == "txt":
                with open(result, encoding="utf-8", errors="replace") as handle:
                    self.office.insert_text(document, handle.read())
            else:
                extra["Document"] = self.office.open_as_new(result)
        except Exception as error:
            return _result("failed", Code="insert", Message=self.t("error.insert", detail=str(error)))
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
        return _result(
            "done",
            ConversionId=str(view.get("id", "")),
            Credits=int(view.get("credits") or 0),
            OutputName=str(view.get("outputName") or ""),
            **extra,
        )

    def _configure(self, args):
        try:
            values = self.office.read_settings()
            changes = {}
            if "BaseUrl" in args:
                changes["BaseUrl"] = settings.normalize_base_url(args["BaseUrl"])
            if "MaxCredits" in args:
                changes["MaxCredits"] = settings.normalize_max_credits(args["MaxCredits"])
            if "OcrLanguage" in args:
                changes["OcrLanguage"] = settings.normalize_language(args["OcrLanguage"])
            if "OcrOutput" in args:
                changes["OcrOutput"] = settings.normalize_output(args["OcrOutput"])
            if changes:
                self.office.write_settings(changes)
            where = ""
            if "ApiKey" in args:
                base = changes.get("BaseUrl", values["BaseUrl"])
                store = KeyStore(self.office)
                key = settings.normalize_key(args["ApiKey"])
                if key:
                    # A macro never turns on saving passwords: that is the user's choice.
                    where = store.save(base, key, bool(args.get("Remember", True)))
                else:
                    store.remove(base)
                    where = "removed"
        except settings.SettingError as error:
            return _result("failed", Code=error.code, Message=self.t("error." + error.code))
        return _result("done", Key=where)


def _result(status, error=None, catalog=None, **values):
    """A macro's answer: Status ("done", "failed", "canceled"), and Code and Message on failure."""
    if error is not None:
        values.setdefault("Code", error.code)
        values.setdefault("Message", error_text(catalog, error))
    out = [NamedValue("Status", status)]
    out.extend(NamedValue(name, value) for name, value in values.items())
    return tuple(out)
