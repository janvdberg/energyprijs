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

import json
import logging
import re
from pathlib import Path

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from . import cards as _cards

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




# ── Energie-dashboard (user dashboard) aanmaken/bijwerken ─────────────────

def _manifest_version(hass: HomeAssistant) -> str:
    """Lees de versie uit de eigen manifest.json (single source of truth)."""
    try:
        from importlib.metadata import version
        return version("energyprijs")
    except Exception:  # noqa: BLE001
        mf = Path(__file__).parent / "manifest.json"
        try:
            return str(json.loads(mf.read_text(encoding="utf-8")).get("version", "0"))
        except Exception:  # noqa: BLE001
            return "0"

DASH_ID = "energyprijs"
DASH_TITEL = "Energie — stroomprijs"
DASH_ICOON = "mdi:flash"

async def _dashboard_opslaan(hass: HomeAssistant) -> dict:
    """Maak het user dashboard aan, of werk de twee energyprijs-kaarten bij.

    Eerbiedig: andere kaarten in het dashboard blijven intact; alleen de
    blokken tussen de energyprijs-markers worden herschreven.
    """
    from .cards import GRAFIEK_CARD, CONTRACT_CARD

    versie = _manifest_version(hass)
    # Beide kaarten als LOSSE YAML-documenten, gemarkeerd met YAML-commentaar
    # (HTML-commentaar faalt als het direct vóór "---" staat — dat is geen
    #  documentgrens meer; YAML-commentaar is parser-proof).
    body = (
        f"# energyprijs:start {versie}\n"
        f"---\n"
        f"{_cards._yaml_dump(GRAFIEK_CARD)}\n"
        f"---\n"
        f"{_cards._yaml_dump(CONTRACT_CARD)}\n"
        f"# energyprijs:einde {versie}\n"
    )

    dash_path = "local/energyprijs-dashboard.yaml"
    # bestaand dashboard ontdekken door .storage/dashboards te scannen
    # (publieke locatie; bevat per dashboard: id, filename, name, require_admin…)
    existing = None
    try:
        store = hass.config.path(".storage/dashboards")
        data = json.loads(Path(store).read_text(encoding="utf-8"))
        for entry in (data.get("data") or {}).get("entries", []):
            if entry.get("id") == DASH_ID:
                existing = entry
                break
    except FileNotFoundError:
        pass
    except Exception:  # noqa: BLE001
        _LOGGER.exception("energyprijs: .storage/dashboards niet te lezen")

    if existing is None:
        # nieuw user dashboard aanmaken via de publieke dashboard.create-service
        # (filename mag niet bestaan; HA maakt het in local/…)
        resp = await hass.services.async_call(
            "dashboard", "create",
            {
                "id": DASH_ID,
                "name": DASH_TITEL,
                "icon": DASH_ICOON,
                "filename": "local/energyprijs-dashboard.yaml",
                "require_admin": False,
                "show_in_menu": True,
            },
            blocking=True, return_response=True,
        ) or {}
        filename = resp.get("filename") or dash_path
        target = Path(hass.config.path()) / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        # Losse YAML-documenten (HA leest multi-document dashboard-bestanden):
        # doc 1 = dashboard-metadata, doc 2 = grafiek-kaart, doc 3 = contract-kaart.
        # Gemarkeerd blok = beide kaart-documenten, inclusief "---" (upgrade-proof).
        content = (
            "title: " + DASH_TITEL + "\n"
            "icon: " + DASH_ICOON + "\n"
            "require_admin: false\n"
            "show_in_menu: true\n"
            "max_width: 900px\n"
            "\n"
            f"# energyprijs:start {versie}\n"
            f"---\n"
            f"{_cards._yaml_dump(GRAFIEK_CARD)}\n"
            f"---\n"
            f"{_cards._yaml_dump(CONTRACT_CARD)}\n"
            f"# energyprijs:einde {versie}\n"
        )
        target.write_text(content, encoding="utf-8")
        return {"act": "aangemaakt", "pad": str(target), "kaart_ervbij": True}

    # bestaand → alleen het gemarkeerde blok vervangen
    target = Path(hass.config.path()) / existing.get("filename", dash_path)
    orig = target.read_text(encoding="utf-8") if target.exists() else ""
    pattern = re.compile(
        r"# energyprijs:start [\w.\-]+\n.*?# energyprijs:einde [\w.\-]+\n",
        re.S)
    if pattern.search(orig):
        new = pattern.sub(body, orig, count=1)
        act = "bijgewerkt"
    else:
        # geen marker → beide kaarten toevoegen als losse sectie (rest van dashboard intact)
        new = orig.rstrip() + "\n" + body
        act = "kaarten toegevoegd (geen marker gevonden)"
    target.write_text(new, encoding="utf-8")
    return {"act": act, "pad": str(target), "kaart_ervbij": False}

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

    async def handle_dashboard(call: ServiceCall) -> dict:
        """Maak het user-dashboard aan of werk de kaarten bij."""
        try:
            res = await _dashboard_opslaan(hass)
        except Exception as e:  # noqa: BLE001
            _LOGGER.exception("energyprijs.dashboard mislukt")
            return {"ok": False, "fout": str(e)}
        res["ok"] = True
        res["uitleg"] = (
            "Dashboard 'Energie — stroomprijs' staat nu in je dashboardmenu. "
            "Bij een volgende upgrade werk ik alleen de gemarkeerde blokken bij."
        )
        return res

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
        DOMAIN, "dashboard", handle_dashboard,
        supports_response=SupportsResponse.OPTIONAL,
    )

    hass.services.async_register(
        DOMAIN, "status", handle_status, supports_response=SupportsResponse.ONLY,
    )
