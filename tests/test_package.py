"""The extension's package: what LibreOffice and the extensions site read from it."""

import ast
import importlib.util
import os
import re
import unittest
import xml.etree.ElementTree as ET

from converterstudio import VERSION

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXTENSION = os.path.join(ROOT, "extension")
NS = {
    "d": "http://openoffice.org/extensions/description/2006",
    "l": "http://libreoffice.org/extensions/description/2011",
    "oor": "http://openoffice.org/2001/registry",
    "c": "http://openoffice.org/2010/uno-components",
}
XLINK = "{http://www.w3.org/1999/xlink}href"


def load_build():
    spec = importlib.util.spec_from_file_location("build", os.path.join(ROOT, "tools", "build.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PackageTest(unittest.TestCase):
    def test_the_build_check_finds_nothing(self):
        self.assertEqual(load_build().check(), [])

    def test_description(self):
        root = ET.parse(os.path.join(EXTENSION, "description.xml")).getroot()
        self.assertEqual(root.find("d:identifier", NS).get("value"), "studio.converter.libreoffice")
        self.assertEqual(root.find("d:version", NS).get("value"), VERSION)
        publisher = root.find("d:publisher/d:name", NS)
        self.assertEqual(
            (publisher.text, publisher.get(XLINK)), ("Converter Studio", "https://converter.studio")
        )
        names = {n.get("lang"): n.text for n in root.findall("d:display-name/d:name", NS)}
        self.assertEqual(names["en"], "Converter Studio")
        minimal = root.find("d:dependencies/l:LibreOffice-minimal-version", NS)
        self.assertEqual(minimal.get("value"), "24.2")
        license_ = root.find("d:registration/d:simple-license", NS)
        self.assertEqual(license_.get("accept-by"), "user")
        update = root.find("d:update-information/d:src", NS).get(XLINK)
        self.assertTrue(
            update.startswith("https://raw.githubusercontent.com/tariksucu/libreoffice-converter-studio/")
        )

    def test_every_menu_command_exists(self):
        root = ET.parse(os.path.join(EXTENSION, "Addons.xcu")).getroot()
        urls = [
            value.text for value in root.iter("value") if value.text and value.text.startswith("service:")
        ]
        commands = {url.split("?", 1)[1] for url in urls}
        self.assertEqual(commands, {"insertPicture", "recognizeText", "openEbook", "settings"})
        for url in urls:
            self.assertTrue(url.startswith("service:studio.converter.libreoffice.Commands?"), url)
        with open(
            os.path.join(EXTENSION, "pythonpath", "converterstudio", "office.py"), encoding="utf-8"
        ) as handle:
            office = handle.read()
        for command in commands:
            self.assertIn('"%s"' % command, office)

    def test_every_menu_title_is_in_english_and_turkish(self):
        root = ET.parse(os.path.join(EXTENSION, "Addons.xcu")).getroot()
        for prop in root.iter("prop"):
            if prop.get("{%s}name" % NS["oor"]) == "Title":
                languages = {
                    value.get("{http://www.w3.org/XML/1998/namespace}lang") for value in prop.findall("value")
                }
                self.assertEqual(languages, {"en-US", "tr"})

    def test_the_component_is_registered_under_its_name(self):
        root = ET.parse(os.path.join(EXTENSION, "converter_studio.components")).getroot()
        component = root.find("c:component", NS)
        self.assertEqual(component.get("loader"), "com.sun.star.loader.Python")
        self.assertEqual(component.get("uri"), "converter_studio.py")
        implementation = component.find("c:implementation", NS)
        with open(os.path.join(EXTENSION, "converter_studio.py"), encoding="utf-8") as handle:
            source = handle.read()
        name = re.search(r'IMPLEMENTATION = "([^"]+)"', source).group(1)
        self.assertEqual(implementation.get("name"), name)
        self.assertEqual(implementation.find("c:service", NS).get("name"), name)

    def test_settings_schema_matches_the_defaults(self):
        from converterstudio import settings

        root = ET.parse(os.path.join(EXTENSION, "Settings.xcs")).getroot()
        props = {p.get("{%s}name" % NS["oor"]): p.find("value").text for p in root.iter("prop")}
        self.assertEqual(set(props), set(settings.DEFAULTS))
        for name, default in settings.DEFAULTS.items():
            self.assertEqual(props[name], str(default), name)

    def test_python_reads_on_old_libreoffice_pythons(self):
        # LibreOffice 24.2's own builds bring Python 3.8 or later: no newer syntax.
        for folder, _dirs, names in os.walk(EXTENSION):
            for name in names:
                if name.endswith(".py"):
                    path = os.path.join(folder, name)
                    with open(path, encoding="utf-8") as handle:
                        ast.parse(handle.read(), path, feature_version=(3, 8))

    def test_icons_are_png_of_the_right_size(self):
        for name in ("converter-studio.png", "converter-studio-hc.png"):
            with open(os.path.join(EXTENSION, "icons", name), "rb") as handle:
                head = handle.read(24)
            self.assertEqual(head[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(
                (int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")), (42, 42)
            )


if __name__ == "__main__":
    unittest.main()
