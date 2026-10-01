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

import asyncio
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
    """Maak het user-dashboard aan of werk het bij — via HA's eigen collecties.

    User dashboards leven in HA-storage (geen los YAML-bestand):
      - .storage/lovelace_dashboards        → dashboard-metadata (DashboardsCollection)
      - .storage/lovelace.<dashboard-id>    → de kaartconfig (LovelaceStorage.async_save)

    We gebruiken daarvoor exact HA's publieke helpers, zodat panel + cache +
    lovelace_updated-event netjes meeliften en het dashboard direct zichtbaar is.
    """
    from .cards import CONTRACT_CARD, GRAFIEK_CARD

    # ── 1) dashboard-metadata: via HA's eigen lovelace-storage (met de live
    #    panel-registratie erbij). De draaiende DashboardsCollection is niet
    #    publiek te bereiken, dus bouwen we een tweede instance op exact dezelfde
    #    storage-key (.storage/lovelace_dashboards): itemids sluiten op elkaar aan
    #    (generate_id) en het add-change wordt zo netjes afgehandeld als via de UI
    #    (panel laten verlopen + storingen opschonen). Panel en kaartconfig voegen
    #    we daarna zelf toe via de publieke frontend/lovelace-helpers. ──
    from homeassistant.components import frontend
    from homeassistant.components.lovelace import dashboard as lb_dash
    from homeassistant.components.lovelace.const import LOVELACE_DATA

    lov_data = hass.data.get(LOVELACE_DATA)
    if lov_data is None:
        raise RuntimeError(
            "Lovelace-integratie is niet actief — kan geen user-dashboard beheren."
        )

    # Maak een foute panel-registratie onschadelijk (bv. overgebleven van een eerdere
    # versie van deze integratie): het re-registeren mag dan opnieuw slagen.
    frontend.async_remove_panel(hass, DASH_ID, warn_if_unknown=False)

    coll = lb_dash.DashboardsCollection(hass)
    await coll.async_load()

    existing = next((it for it in coll.data.values() if it.get("url_path") == DASH_ID), None)

    async def _flush_collection_save() -> None:
        """De collectie-save van HA zit op een timer van 10 s.

        Onmiddellijk flushen (delay=0) voorkomt dat de dashboard-metadata pas
        later — of helemaal niet, bij een tussentijdse herstart — op disk staat.
        """
        try:
            coll.store.async_delay_save(coll._data_to_save, 0)  # noqa: SLF001
            await hass.async_block_till_done()
        except Exception:  # noqa: BLE001
            pass

    if existing is None:
        try:
            entry = await coll.async_create_item({
                "url_path": DASH_ID,
                "mode": "storage",
                "title": DASH_TITEL,
                "icon": DASH_ICOON,
                "show_in_sidebar": True,
                "require_admin": False,
                "allow_single_word": True,
            })
        except Exception as err:  # noqa: BLE001
            raise RuntimeError(f"dashboard aanmaken mislukt: {err}") from err
        act = "aangemaakt"
        await _flush_collection_save()
        # panel zo snel mogelijk tonen; dit heeft geen effect op de luchtige
        # dashboard-view (mode "storage" haalt de content uit storage)
        try:
            frontend.async_register_built_in_panel(
                hass, "lovelace",
                frontend_url_path=DASH_ID,
                sidebar_title=DASH_TITEL,
                sidebar_icon=DASH_ICOON,
                require_admin=False,
                config={"mode": "storage"},
                update=True,
            )
        except Exception:  # noqa: BLE001
            pass
    else:
        entry = existing
        act = "bijgewerkt"
        try:
            frontend.async_register_built_in_panel(
                hass, "lovelace",
                frontend_url_path=DASH_ID,
                sidebar_title=DASH_TITEL,
                sidebar_icon=DASH_ICOON,
                require_admin=False,
                config={"mode": "storage"},
                update=True,
            )
        except ValueError:
            pass
        except Exception:  # noqa: BLE001
            pass

    dash_id = entry["id"]

    # ── 2) kaartconfig: .storage/lovelace.<id> via LovelaceStorage (public API) ──
    from homeassistant.components.lovelace.const import ConfigNotFound

    store = lb_dash.LovelaceStorage(hass, entry)
    try:
        cfg = await store.async_load(force=False)
    except ConfigNotFound:
        cfg = None
    # async_save vereist een gevulde cache (_data) — async_load vulde 'm al wanneer
    # de storage bestond; bij ConfigNotFound (nog nooit opgeslagen) blijft ie None,
    # waarna async_save zelf _load() aanroept.

    # ── 0) voorkans: het package (helpers + templates) moet geïnstalleerd zijn,
    #    anders tonen de kaarten alleen onbeschikbare entiteiten ──
    from homeassistant.helpers import entity_registry as er

    ent_reg = er.async_get(hass)
    if "input_number.prijs_btw" not in {e.entity_id for e in ent_reg.entities.values()}:
        raise RuntimeError(
            "De energie-helpers (input_number.prijs_btw …) ontbreken nog. "
            "Draai eerst de service energyprijs.install en herstart Home Assistant, "
            "voordat je dit dashboard vult."
        )

    views = (cfg or {}).get("views") or [{"title": "Energie", "path": "energie", "cards": []}]
    first = views[0]
    # user dashboards worden in de UI als SECTIE-view aangemaakt ("New section");
    # secties hebben een nested structuur en kunnen niet direct losse kaarten dragen.
    # Onze kaarten zijn gewone cards → normaliseer naar een klassieke card-view.
    if first.get("type") == "sections" or any(
            isinstance(c, dict) and c.get("type") in ("section", "grid")
            for c in (first.get("cards") or [])):
        flat_cards = []
        for c in first.get("cards") or []:
            if isinstance(c, dict) and c.get("type") in ("section", "grid"):
                flat_cards.extend(c.get("cards") or [])
            else:
                flat_cards.append(c)
        first.pop("type", None)
        first["cards"] = flat_cards
    cards_list = first.get("cards") or []

    # onze kaarten herkennen op hun unieke entiteiten; rest blijft intact
    def _is_ours(card) -> bool:
        if not isinstance(card, dict):
            return False
        t = card.get("type")
        if t == "custom:apexcharts-card":
            ents = {x.get("entity") for x in card.get("series", []) if isinstance(x, dict)}
            return "sensor.stroomprijs_daglijst" in ents
        if t == "entities":
            ents = {c.get("entity") if isinstance(c, dict) else c for c in card.get("entities", [])}
            return "input_number.prijs_btw" in ents
        return False

    kept = [c for c in cards_list if not _is_ours(c)]
    removed = len(cards_list) - len(kept)
    first["cards"] = kept + [GRAFIEK_CARD, CONTRACT_CARD]

    new_cfg = {"views": views}
    if (cfg or {}).get("jinja"):
        new_cfg["jinja"] = cfg["jinja"]
    await store.async_save(new_cfg)   # vuurt lovelace_updated af → frontend ververst

    return {
        "act": act,
        "dashboard_id": dash_id,
        "verwijderde_eigen_oude_kaarten": removed,
        "totaal_cards_eerste_view": len(first["cards"]),
        "url_path": DASH_ID,
    }


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
