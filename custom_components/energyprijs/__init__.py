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
    dashboard_bestaat_hier,
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
    "input_number.prijs_btw",
    "input_number.prijs_energiebelasting",
    "input_number.prijs_opslag_afname",
    "input_number.prijs_opslag_levering",
    "input_number.prijs_afwijkingsdrempel",
    "input_number.prijs_laad_drempel",
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

    async def _auto_dashboard(_now=None) -> None:
        """Zorg dat het energie-dashboard klopt na een UPDATE van deze integratie.

        Policy (na overleg met de gebruiker, sep '26):
          - Nooit elke 5 min aanmaken/bijwerken.
          - Wél: bij setup (dus na een HACS-update + herstart/reload) én zolang
            het dashboard ONTBREEKT om de 5 min proberen aan te maken. Bestaat
            het eenmaal op de huidige manifest-versie, dan doet de timer niets
            meer — alleen kaarten-updates via de service blijven mogelijk.
        """
        from homeassistant.components.lovelace.const import LOVELACE_DATA

        if hass.data.get(LOVELACE_DATA) is None:
            return  # lovelace nog niet actief — volgende ronde probeert opnieuw

        manifest_version = _manifest_version(hass)
        bestaand = entry.data.get("dashboard_versie")

        # Dashboard bestaat al in HA en de versie-tag op de view klopt → klaar.
        if await dashboard_bestaat_hier(hass):
            try:
                res = await _dashboard_opslaan(hass)
                if res.get("act") == "huidig":
                    if bestaand != manifest_version:
                        try:
                            hass.config_entries.async_update_entry(
                                entry, data={**entry.data, "dashboard_versie": manifest_version}
                            )
                        except Exception:  # noqa: BLE001
                            pass
                    unsub2()  # timer stop: er is niets meer automatisch te doen
                    return
            except Exception:  # noqa: BLE001
                pass  # helpers/package nog niet geladen; timer komt terug

        # Dashboard ontbreekt of is verouderd → (her)bouwen.
        try:
            res = await _dashboard_opslaan(hass)
            _LOGGER.info("energyprijs: dashboard onderhouden → %s", res.get("act"))
            if res.get("act") in ("aangemaakt", "bijgewerkt"):
                try:
                    hass.config_entries.async_update_entry(
                        entry, data={**entry.data, "dashboard_versie": manifest_version}
                    )
                except Exception:  # noqa: BLE001
                    pass
                unsub2()  # geslaagd → timer uit; bij falen blijft hij elke 5 min proberen
        except Exception:  # noqa: BLE001
            _LOGGER.debug("energyprijs: dashboard nog niet gereed — later opnieuw",
                          exc_info=True)

    async def _watcher(_now) -> None:
        _try_link()
        reg = er.async_get(hass)
        aanwezig = sum(
            1 for p, uid in TEMPLATE_UNIQUE_IDS if reg.async_get_entity_id(p, "template", uid)
        ) + sum(1 for eid in HELPER_ENTITY_IDS if reg.async_get(eid))
        if aanwezig >= totaal:
            unsub()

    unsub = async_track_time_interval(hass, _watcher, timedelta(minutes=30))
    entry.async_on_unload(unsub)

    # dashboard-onderhoud: één keer rustig na startup (lovelace + template-
    # entiteiten moeten geregistreerd zijn) en daarna als back-up elke 5 min
    hass.async_create_task(_auto_dashboard())
    unsub2 = async_track_time_interval(hass, _auto_dashboard, timedelta(minutes=5))
    entry.async_on_unload(unsub2)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Nothing to unload — we own no platforms."""
    return True
