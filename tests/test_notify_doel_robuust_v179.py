"""v1.7.9: notify-doel-template mag NOOIT 'notify.unknown' opleveren.

Reparatie (repair 'unknown action notify.unknown'): de oude één-regel-vorm
  {{ 'notify.' ~ (states('input_text.prijs_notify_doel') or 'persistent_notification') }}
geeft 'notify.unknown' zodra de helper unknown/unavailable is (rond herstart/
update) — 'unknown' is een niet-lege string, dus de `or`-fallback wordt
overgeslagen en de actie bestaat niet.

Deze test dwingt af: elke templated notify-action in package én shadow gebruikt
de robuuste trim/not-in-vorm, en géén enkele plaats bevat nog de kwetsbare vorm.
"""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PKG_PATH = ROOT / "custom_components" / "energyprijs" / "package.yaml"
SHADOW_PATH = ROOT / "custom_components" / "energyprijs" / "shadow" / "shadow.yaml"

ROBUUST = "'unknown', 'unavailable', 'none'"
KWETSBARE = "'notify.' ~ (states('input_text.prijs_notify_doel') or 'persistent_notification')"


def _notify_template_actions(path):
    pkg = yaml.safe_load(path.read_text(encoding="utf-8"))
    out = []
    for auto in pkg.get("automation", []):
        aid = auto.get("id", auto.get("alias", "?"))
        for act in auto.get("actions", []) or []:
            if isinstance(act, dict):
                action = act.get("action")
                if isinstance(action, str) and "notify." in action and "{{" in action:
                    out.append((aid, action))
    return out


def test_geen_kwetsbare_or_fallback_meer():
    for path in (PKG_PATH, SHADOW_PATH):
        raw = path.read_text(encoding="utf-8")
        assert KWETSBARE not in raw, (
            f"{path.name}: oude 'or'-fallback staat er nog — geeft "
            "notify.unknown bij unknown/unavailable helper")


def test_elke_notify_action_is_robuust():
    for path in (PKG_PATH, SHADOW_PATH):
        actions = _notify_template_actions(path)
        assert actions, f"{path.name}: geen enkele notify-template-actie gevonden"
        for aid, action in actions:
            assert "| trim" in action, f"{aid}: mist trim van de helper"
            assert ROBUUST in action, (
                f"{aid}: fallback vangt unknown/unavailable niet af")


def test_package_yaml_parses_en_helper_bestaat():
    pkg = yaml.safe_load(PKG_PATH.read_text(encoding="utf-8"))
    assert "prijs_notify_doel" in pkg.get("input_text", {})
    ids = {a.get("id") for a in pkg["automation"]}
    assert {"prijzen_meld_bronuitval", "prijzen_meld_morgen_missing",
            "prijzen_meld_nettoeslag_blokken"} <= ids
