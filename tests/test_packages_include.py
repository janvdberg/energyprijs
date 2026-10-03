"""Test: _ensure_packages_include plaatst het blok ALTIJD op kolom 0.

Reproduceert het live-valkuil (okt 2026): includes ingesprongen onder een
toplevel default_config:-blok → installer sloop zijn homeassistant:-blok erachter
→ YAML zag het als default_config-optie → HA negeerde packages stil.
"""
from pathlib import Path

from custom_components.energyprijs.installer import _ensure_packages_include_sync as _ensure_packages_include

JANS_CFG = """# Configure a default setup of Home Assistant
default_config:

  automation: !include automations.yaml
  script: !include scripts.yaml

  # --- energyprijs installer: packages ondersteund door Home Assistant
  homeassistant:
    packages: !include_dir_named packages
  # --- einde energyprijs installer ---
"""


def test_misplaced_block_gets_fixed(tmp_path: Path) -> None:
    cfg = tmp_path / "configuration.yaml"
    cfg.write_text(JANS_CFG, encoding="utf-8")

    changed, note = _ensure_packages_include(cfg)
    assert changed is True
    text = cfg.read_text(encoding="utf-8")
    lines = text.splitlines()
    idx = next(i for i, ln in enumerate(lines) if ln == "homeassistant:")
    assert not lines[idx].startswith(" "), "homeassistant: moet op kolom 0 staan"
    assert lines[idx + 1] == "  packages: !include_dir_named packages"
    # geen losse dubbele blokken achterlaten
    assert text.count("homeassistant:") == 1
    # de bestaande includes blijven intact
    assert "automation: !include automations.yaml" in text


def test_correct_block_is_idempotent(tmp_path: Path) -> None:
    cfg = tmp_path / "configuration.yaml"
    cfg.write_text(
        "# kop\nhomeassistant:\n  packages: !include_dir_named packages\n",
        encoding="utf-8",
    )
    changed, note = _ensure_packages_include(cfg)
    assert changed is False
    assert cfg.read_text(encoding="utf-8").count("packages:") == 1


def test_fresh_file_gets_top_level_block(tmp_path: Path) -> None:
    cfg = tmp_path / "configuration.yaml"
    cfg.write_text("default_config:\n\nhttp:\n  base_url: x\n", encoding="utf-8")
    changed, _ = _ensure_packages_include(cfg)
    assert changed is True
    assert "\nhomeassistant:\n  packages: !include_dir_named packages\n" in cfg.read_text(encoding="utf-8")
