"""Converter Studio for LibreOffice.

The modules of this package that do not start with ``office`` need nothing but the Python standard
library, so they run (and are tested) outside LibreOffice too. ``office`` holds everything that
talks to LibreOffice through UNO.
"""

# Kept equal to <version> in description.xml (a unit test checks it).
VERSION = "1.0.0"

# Names this extension to the API (X-Converter-Studio-Client), for converter.studio's statistics.
CLIENT = "libreoffice"

SITE = "https://converter.studio"
DEFAULT_BASE_URL = SITE + "/api"
KEYS_PAGE = SITE + "/account#api-keys"
PRIVACY_PAGE = SITE + "/privacy"
PRICING_PAGE = SITE + "/pricing"
