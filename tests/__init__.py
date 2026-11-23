import os
import sys

# The extension's own modules, as LibreOffice finds them (its pythonpath folder).
sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "extension", "pythonpath")
)
