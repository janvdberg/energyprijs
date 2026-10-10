"""Validatie: het SHADOW-package moet door HA's eigen schema's.

De E2E-test (test_shadow_package.py) laadt het package via HA's template-
component — maar die accepteert óók lichte onregelmatigheden die in de
productie-config niet doorlopen. Deze test valideert expliciet:
- input_number-schema's (alle shadow-helpers, incl. shadow_hysteresis)
- input_text-schema (shadow_vorige_status)
- template-CONFIG via async_validate_config

Zodra een helper de HA-validatie faalt (typo in een key, onjuiste range),
faalt deze test — vóórdat de installer het package naar /config/packages/
schrijft en Jan een herstart nodig heeft.
"""
from pathlib import Path

import yaml
from homeassistant.components import input_number, input_text
from homeassistant.components.template import config as tcfg

SHADOW_PATH = (Path(__file__).resolve().parents[1]
               / "custom_components" / "energyprijs" / "shadow" / "shadow.yaml")


async def test_shadow_input_number_valid(hass):
    pkg = yaml.safe_load(SHADOW_PATH.read_text(encoding="utf-8"))
    assert "input_number" in pkg, "shadow.yaml mist het input_number-blok"
    for name, cfg in pkg["input_number"].items():
        validated = input_number.CONFIG_SCHEMA({"input_number": {name: cfg}})
        assert "input_number" in validated, f"{name} faalt HA-validatie"


def test_shadow_input_text_valid():
    pkg = yaml.safe_load(SHADOW_PATH.read_text(encoding="utf-8"))
    assert "input_text" in pkg, "shadow.yaml mist het input_text-blok"
    for name, cfg in pkg["input_text"].items():
        validated = input_text.CONFIG_SCHEMA({"input_text": {name: cfg}})
        assert "input_text" in validated, f"{name} faalt HA-validatie"


async def test_shadow_template_valid(hass):
    pkg = yaml.safe_load(SHADOW_PATH.read_text(encoding="utf-8"))
    assert "template" in pkg, "shadow.yaml mist het template-blok"
    out = await tcfg.async_validate_config(hass, {"template": pkg["template"]})
    assert out.get("template"), "HA accepteert het shadow-templateblok niet"


def test_shadow_automation_trigger_vennige():
    """v1.5.2: de log-automation moet from/to/fan_is_not combineren.

    HA 2026.x: `not` is deprecated; de combinatie from + to + from_is_not
    is de correcte vorm. De oude `not: "unavailable"`-vorm telde óók
    onbekend→bekend-overgangen mee (het kwartier-index-gap-probleem).
    """
    pkg = yaml.safe_load(SHADOW_PATH.read_text(encoding="utf-8"))
    assert "automation" in pkg, "shadow.yaml mist het automation-blok"
    log_auto = next(a for a in pkg["automation"]
                    if a.get("id") == "energyprijs_shadow_log")
    trig = log_auto["triggers"][0]
    assert trig.get("trigger") == "state"
    # De nieuwe vorm: from + to + from_is_not, géén oude `not`-key
    assert "from" in trig and "to" in trig, (
        "log-automation moet from+to gebruiken (v1.5.2), "
        f"got keys: {list(trig.keys())}")
    assert trig.get("from_is_not") == "unavailable"
    assert "not" not in trig, "oude `not`-key is deprecated — weg ermee"
