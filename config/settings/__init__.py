"""
Settings package - selects dev or production based on DJANGO_SETTINGS_MODULE.
Default to dev if not specified.
"""

import os

if os.environ.get("DJANGO_SETTINGS_MODULE", "").endswith(".production"):
    from .production import *
else:
    from .dev import *