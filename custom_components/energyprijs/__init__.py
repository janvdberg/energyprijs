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

from .const import DOMAIN
from .installer import async_register_services

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
        sw_version="1.2.4",
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
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Nothing to unload — we own no platforms."""
    return True
