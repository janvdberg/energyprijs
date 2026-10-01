"""Energyprijs — installer-integratie.

Schrijft het stroomprijs-package naar /config/packages/ en bewaakt
configuration.yaml op de packages-include. De entiteiten zelf komen uit het
YAML-package; deze integratie koppelt ze alleen zichtbaar aan de config-entry
(één device + entity_registry-links), zodat de integratiepagina niet leeg blijft.
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType

from datetime import timedelta

import json as _json
from pathlib import Path as _Path

from .const import DOMAIN

_MANIFEST = _json.loads((_Path(__file__).parent / "manifest.json").read_text(encoding="utf-8"))
_VERSION = str(_MANIFEST.get("version", "0"))
from .installer import (
    async_register_services,
    _dashboard_opslaan,
    _manifest_version,
)

_LOGGER = logging.getLogger(__name__)

# Entiteiten die het package aanmaakt, mirroring package.yaml.
# Template-entiteiten hebben een unique_id → koppelen op (platform, unique_id).
# Helpers (input_number/input_boolean) hebben géén unique_id → op entity_id.
TEMPLATE_UNIQUE_IDS: list[tuple[str, str]] = [
    ("sensor", "prijzen_bron_nordpool"),
    ("sensor", "prijzen_bron_enerprice"),
    ("sensor", "prijzen_bron_energyzero"),
    ("sensor", "stroomprijs_basis"),
    ("sensor", "stroomprijs_daglijst"),
    ("sensor", "stroomprijs_afname"),
    ("sensor", "stroomprijs_levering"),
    ("binary_sensor", "prijzen_kruiscontrole_afwijking"),
    ("binary_sensor", "prijzen_morgen_beschikbaar"),
]

HELPER_ENTITY_IDS: list[str] = [
    "input_text.prijs_btw",
    "input_text.prijs_energiebelasting",
    "input_text.prijs_opslag_afname",
    "input_text.prijs_opslag_levering",
    "input_text.prijs_afwijkingsdrempel",
    "input_text.prijs_laad_drempel",
    "input_boolean.prijs_saldering_energiebelasting_teruggave",
]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Registreer de installatieservices."""
    await async_register_services(hass)
    return True


@callback
def _link_entities(hass: HomeAssistant, entry: ConfigEntry, device_id: str) -> int:
    """Koppel package-entiteiten aan de config-entry + device. Idempotent."""
    reg = er.async_get(hass)
    gekoppeld = 0
    for platform, uid in TEMPLATE_UNIQUE_IDS:
        # registry-sleutel is (platform, domain, unique_id); bij template-
        # entiteiten is platform == domein van de entiteit zelf.
        eid = reg.async_get_entity_id(platform, "template", uid)
        if eid is None:
            continue
        ent = reg.async_get(eid)
        if ent is not None and ent.config_entry_id != entry.entry_id:
            try:
                reg.async_update_entity(eid, config_entry_id=entry.entry_id, device_id=device_id)
                gekoppeld += 1
            except Exception:  # noqa: BLE001
                _LOGGER.debug("energyprijs: koppelen %s mislukt", eid)
    for eid in HELPER_ENTITY_IDS:
        ent = reg.async_get(eid)
        if ent is not None and ent.config_entry_id != entry.entry_id:
            try:
                reg.async_update_entity(eid, config_entry_id=entry.entry_id, device_id=device_id)
                gekoppeld += 1
            except Exception:  # noqa: BLE001
                _LOGGER.debug("energyprijs: koppelen %s mislukt", eid)
    return gekoppeld


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Registreer services + maak het apparaat + koppel entiteiten aan de entry."""
    await async_register_services(hass)

    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "energyprijs-package")},
        name="Energyprijs package",
        manufacturer="Energyprijs",
        model="3-bronnen stroomprijs-package",
        sw_version=_VERSION,
    )

    # Het package wordt pas bij een herstart geladen; direct na installeren
    # bestaan de entiteiten dus nog niet. Koppel wat er is en probeer het
    # daarna elk half uur opnieuw tot alles onder het device staat.
    totaal = len(TEMPLATE_UNIQUE_IDS) + len(HELPER_ENTITY_IDS)

    @callback
    def _try_link(_=None) -> None:
        n = _link_entities(hass, entry, device.id)
        if n:
            _LOGGER.info("energyprijs: %d package-entiteiten gekoppeld", n)

    _try_link()

    # Zet een herkenbare titel op de entry → de integratie-tegel linkt naar de services
    try:
        if entry.title != "Energyprijs":
            hass.config_entries.async_update_entry(entry, title="Energyprijs")
    except Exception:  # noqa: BLE001
        pass

    # ── 5-min back-up timer: alleen zolang het dashboard niet op de huidige
    #    manifest-versie staat. Biedt vangnet als het package te laat laadt.
    # ────────────────────────────────────────────────────────────────────────
    async def _auto_dashboard(_now=None) -> None:
        from homeassistant.components.lovelace.const import LOVELACE_DATA

        if not hass.is_running:
            return
        if hass.data.get(LOVELACE_DATA) is None:
            return

        # Package moet klaar zijn
        reg = er.async_get(hass)
        if reg.async_get("input_text.prijs_btw") is None:
            return

        manifest_version = _manifest_version(hass)
        if entry.data.get("dashboard_versie") == manifest_version:
            return  # al op de juiste versie

        try:
            res = await _dashboard_opslaan(hass)
            _LOGGER.info("energyprijs: dashboard back-up → %s", res.get("act"))
            if res.get("act") in ("aangemaakt", "bijgewerkt", "huidig"):
                hass.config_entries.async_update_entry(
                    entry, data={**entry.data, "dashboard_versie": manifest_version}
                )
        except Exception:  # noqa: BLE001
            _LOGGER.debug("energyprijs: dashboard nog niet gereed — later opnieuw",
                          exc_info=True)

    # ── Startup-orchestratie (les uit WrtManager #156 + HA core #165767):
    #    Pas nadat HA volledig is gestart (EVENT_HOMEASSISTANT_STARTED) maken we
    #    dashboards/resources aan — anders raast dat concurrent met andere
    #    integraties en de laatste schrijver wint.
    #
    #    Volgorde:
    #      1. EVENT_HOMEASSISTANT_STARTED (of direct als HA al draait bij reload)
    #      2. Package-control: input_text.prijs_btw MOET in de registry staan
    #      3. Pas dan _dashboard_opslaan (DashboardsCollection + LovelaceStorage)
    #      4. 5-min back-up timer alleen zolang het nog niet is geslaagd
    #
    from homeassistant.core import EVENT_HOMEASSISTANT_STARTED

    def _package_klaar() -> bool:
        reg = er.async_get(hass)
        return reg.async_get("input_text.prijs_btw") is not None

    async def _startup_dashboard(_event=None) -> None:
        _LOGGER.debug("energyprijs: dashboard-check bij startup")
        if not _package_klaar():
            _LOGGER.info("energyprijs: package nog niet geladen; dashboard later")
            return
        try:
            res = await _dashboard_opslaan(hass)
            _LOGGER.info("energyprijs: dashboard bij startup → %s", res.get("act"))
            if res.get("act") in ("aangemaakt", "bijgewerkt", "huidig"):
                try:
                    hass.config_entries.async_update_entry(
                        entry, data={**entry.data, "dashboard_versie": _manifest_version(hass)}
                    )
                except Exception:  # noqa: BLE001
                    pass
        except Exception:  # noqa: BLE001
            _LOGGER.debug("energyprijs: dashboard nog niet gereed — 5-min timer overneemt",
                          exc_info=True)

    if hass.is_running:
        # Entry-reload tijdens draaiende HA: dashboard direct checken
        hass.async_create_task(_startup_dashboard())
    else:
        hass.bus.async_listen_once(
            EVENT_HOMEASSISTANT_STARTED, _startup_dashboard
        )

    # 5-min back-up: alleen actief zolang het dashboard niet op de huidige
    # manifest-versie staat. Biedt vangnet als het package te laat laadt.
    unsub2 = async_track_time_interval(hass, _auto_dashboard, timedelta(minutes=5))
    entry.async_on_unload(unsub2)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Nothing to unload — we own no platforms."""
    return True
