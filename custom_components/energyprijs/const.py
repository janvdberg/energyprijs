"""Constanten voor de energyprijs-installer."""
DOMAIN = "energyprijs"
PACKAGE_FILENAME = "energyprijs.yaml"
PACKAGE_SOURCE = "package.yaml"
CONFIG_FILENAME = "configuration.yaml"

import json as _json
from pathlib import Path as _Path

# Één bron voor de versie: het manifest, bij import ingelezen (geen I/O in de
# event-loop en geen importlib.metadata — dat doet per call een listdir).
_MANIFEST = _json.loads((_Path(__file__).parent / "manifest.json").read_text(encoding="utf-8"))
VERSION = str(_MANIFEST.get("version", "0"))
