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


def test_inbestaand_blok_wordt_niet_geschrven_maar_keurde_beoordeeld(tmp_path: Path) -> None:
    """P2-fix 4 okt '26: de installer schrijft NOOIT meer naar configuration.yaml.

    Het oude misplaced-blok (homeassistant: onder default_config:) was precies
    het risico op een dubbele top-level-sleutel. Nu: read-only beoordeling; de
    gebruiker krijgt de te plakken regels in de toelichting.
    """
    cfg = tmp_path / "configuration.yaml"
    before = JANS_CFG
    cfg.write_text(before, encoding="utf-8")

    changed, note = _ensure_packages_include(cfg)
    assert changed is False, "installer mag configuration.yaml niet wijzigen"
    assert cfg.read_text(encoding="utf-8") == before, "bestand is herschreven!"
    # ingesprongen include telt NIET als ok → handmatig met instructie
    assert "[handmatig]" in note
    assert "packages: !include_dir_named packages" in note


def test_correct_block_is_idempotent(tmp_path: Path) -> None:
    cfg = tmp_path / "configuration.yaml"
    cfg.write_text(
        "# kop\nhomeassistant:\n  packages: !include_dir_named packages\n",
        encoding="utf-8",
    )
    changed, note = _ensure_packages_include(cfg)
    assert changed is False
    assert "[ok]" in note


def test_geen_config_en_ui_only(tmp_path: Path) -> None:
    from custom_components.energyprijs.installer import _packages_status_sync

    status, _ = _packages_status_sync(tmp_path / "configuration.yaml")
    assert status == "geen_config"

    ui = tmp_path / "ui"
    (ui / ".storage").mkdir(parents=True)
    (ui / ".storage" / "auth_providers").write_text("{}")
    status, note = _packages_status_sync(ui / "configuration.yaml")
    assert status == "ui_only"


def test_merge_variant_telt_als_ok(tmp_path: Path) -> None:
    """!include_dir_merge_named is een VOLLEDIG geldige packages-route — die mag
    nooit als ontbrekend worden gerapporteerd, laat staan overschreven."""
    from custom_components.energyprijs.installer import _packages_status_sync

    cfg = tmp_path / "configuration.yaml"
    cfg.write_text(
        "homeassistant:\n  packages: !include_dir_merge_named packages\n",
        encoding="utf-8",
    )
    status, _ = _packages_status_sync(cfg)
    assert status == "ok"


def test_bestand_met_andere_keys_krijgt_GEEN_tweede_blok(tmp_path: Path) -> None:
    """De exacte bug uit de review: homeassistant:-blok met alleen name/unit_system.

    Oud gedrag: er werd een TWEEDE top-level homeassistant:-blok ingevoegd →
    ongeldige YAML → HA start niet. Nieuw gedrag: bestand blijft ongemoeid,
    status='handmatig' met plakinstructie.
    """
    from custom_components.energyprijs.installer import _packages_status_sync

    cfg = tmp_path / "configuration.yaml"
    src = ("homeassistant:\n"
           "  name: Thuis\n"
           "  unit_system: metric\n"
           "http:\n  base_url: x\n")
    cfg.write_text(src, encoding="utf-8")

    status, note = _packages_status_sync(cfg)
    assert status == "handmatig"
    assert cfg.read_text(encoding="utf-8") == src, "bestand gewijzigd — verboden"
    assert "homeassistant:" in note and "packages: !include_dir_named packages" in note
