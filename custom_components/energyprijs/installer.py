"""Energyprijs-installer.

Doeboel:
  1. Package-YAML → /config/packages/energyprijs.yaml
  2. configuration.yaml: packages-include garanderen
     (voegt homeassistant: packages: !include_dir_named packages toe als die ontbreekt)
  3. Melding: herstart nodig (of optioneel: automatische herstart)

De package staat ingebed in package.yaml naast dit bestand, zodat de
integratie zelfvoorzienend is (geen netwerk nodig, werkt achter firewalls).
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

try:
    from homeassistant.core import SupportsResponse
except ImportError:  # kern < 2024.4 had 'Optional' i.p.v. 'ONLY/OPTIONAL'
    SupportsResponse = None

from .const import DOMAIN, PACKAGE_FILENAME, PACKAGE_SOURCE, CONFIG_FILENAME

_LOGGER = logging.getLogger(__name__)

CONF_FORCE_RESTART = "force_restart"

INSTALL_SCHEMA = vol.Schema(
    {vol.Optional(CONF_FORCE_RESTART, default=False): cv.boolean},
    extra=vol.ALLOW_EXTRA,
)


def _config_dir(hass: HomeAssistant) -> Path:
    return Path(hass.config.path())


def _write_package(hass: HomeAssistant) -> Path:
    """Schrijf het ingebedde package-bestand weg (idempotent)."""
    packages_dir = _config_dir(hass) / "packages"
    packages_dir.mkdir(parents=True, exist_ok=True)
    target = packages_dir / PACKAGE_FILENAME
    source = Path(__file__).parent / PACKAGE_SOURCE
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return target


def _ensure_packages_include(config_path: Path) -> tuple[bool, str]:
    """Zorg dat configuration.yaml de packages-include heeft.

    Geeft terug (gewijzigd, uitleg).
    """
    original = config_path.read_text(encoding="utf-8") if config_path.exists() else ""

    # Al aanwezig? Zoek naar 'packages:' onder een homeassistant:-blok of los.
    if re.search(r"(?m)^\s*packages\s*:", original):
        return False, "packages-include stond al in configuration.yaml"

    block = (
        "\n# --- energyprijs installer: packages ondersteuning toegevoegd ---\n"
        "homeassistant:\n"
        "  packages: !include_dir_named packages\n"
        "# --- einde energyprijs installer ---\n"
    )

    if not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(block.lstrip("\n"), encoding="utf-8")
        return True, "configuration.yaml aangemaakt met packages-include"

    if re.search(r"(?m)^homeassistant\s*:", original):
        # homeassistant:-blok bestaat al → packages regel toevoegen onder dat blok
        lines = original.splitlines(keepends=True)
        out: list[str] = []
        inserted = False
        in_block = False
        for line in lines:
            if re.match(r"^homeassistant\s*:", line):
                in_block = True
                out.append(line)
                out.append("  packages: !include_dir_named packages\n")
                inserted = True
                continue
            if in_block and re.match(r"^\S", line) and not line.startswith("#"):
                in_block = False
            out.append(line)
        if not inserted:
            out.append(block)
        config_path.write_text("".join(out), encoding="utf-8")
        return True, "packages-include toegevoegd aan bestaand homeassistant:-blok"

    # geen homeassistant:-blok → aan het eind toevoegen
    with config_path.open("a", encoding="utf-8") as f:
        f.write(block)
    return True, "homeassistant:-blok met packages-include toegevoegd"


async def async_register_services(hass: HomeAssistant) -> None:
    """Registreer energyprijs.install en energyprijs.status."""

    async def handle_install(call: ServiceCall) -> dict:
        hass_config = _config_dir(hass)
        cfg_file = hass_config / CONFIG_FILENAME

        # 1) package wegschrijven
        target = _write_package(hass)

        # 2) configuration.yaml bewaken/aanvullen
        changed, note = _ensure_packages_include(cfg_file)

        # 3) status bepalen
        restart_needed = changed
        result = {
            "package_geschreven": str(target),
            "configuration_yaml_gewijzigd": changed,
            "toelichting": note,
            "herstart_nodig": restart_needed,
        }

        if restart_needed and call.data.get(CONF_FORCE_RESTART, False):
            _LOGGER.warning("energyprijs: herstart wordt forcerend geactiveerd")
            await hass.services.async_call("homeassistant", "restart", blocking=False)
            result["herstart_gestart"] = True
        elif restart_needed:
            result["actie"] = (
                "Herstart Home Assistant (Instellingen → Systeem → Herstarten) "
                "om de packages-include te activeren."
            )
        else:
            result["actie"] = "Alles stond al goed; herstart niet nodig."

        _LOGGER.info("energyprijs.install → %s", result)
        return result

    async def handle_cards(call: ServiceCall) -> dict:
        """Geef de kant-en-klare dashboardkaarten (grafiek + contractinvulvelden)."""
        from .cards import build_cards_yaml
        grafiek, contract = build_cards_yaml()
        return {
            "grafiek": grafiek,
            "contract": contract,
            "uitleg": (
                "Plak 'grafiek' via Add card → Show code editor (vereist HACS-kaart "
                "apexcharts-card), en 'contract' als losse entities-tegel. Beide kaarten "
                "zijn volledig dynamisch: sensoren herberekenen direct bij helper-wijziging."
            ),
        }

    async def handle_status(call: ServiceCall) -> dict:
        cfg_file = _config_dir(hass) / CONFIG_FILENAME
        pkg_file = _config_dir(hass) / "packages" / PACKAGE_FILENAME
        cfg = cfg_file.read_text(encoding="utf-8") if cfg_file.exists() else ""
        return {
            "configuration_yaml_bestaat": cfg_file.exists(),
            "packages_include_aanwezig": bool(re.search(r"(?m)^\s*packages\s*:", cfg)),
            "package_bestaat": pkg_file.exists(),
            "package_pad": str(pkg_file),
        }

    hass.services.async_register(
        DOMAIN, "install", handle_install, schema=INSTALL_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )

    hass.services.async_register(
        DOMAIN, "cards", handle_cards,
        supports_response=SupportsResponse.OPTIONAL,
    )

    hass.services.async_register(
        DOMAIN, "status", handle_status, supports_response=SupportsResponse.ONLY,
    )
