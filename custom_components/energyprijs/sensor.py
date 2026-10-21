"""Sensor platform voor de energyprijs-voorspelling (stroomvoorspeller.nl).

Registreert sensor.prijzen_bron_voorspelling — een CoordinatorEntity die
elke 15 min de dag+1-prognose ophaalt en als attributes draagt. De entiteit
is INFORMATIEF: shadowPIES en de 15:15-melding lezen 'morgen' (echte
prijzen), nooit 'morgen_prognose' (prognose).
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_change

from .voorspelling import VoorspellingCoordinator, VoorspellingSensor


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Maak de voorspelling-sensor aan (1 per config-entry).

    De eerste fetch draait direct bij setup (niet na 15 min): een mislukte
    eerste fetch breekt de setup nooit (async_fetch_forecast slikt alle
    fouten → lege lijst), maar zonder deze refresh zou de sensor na elke
    herstart een kwartier unavailable zijn.

    Extra: om 00:00 lokale tijd wordt de coordinator ververst. De fetch
    filtert op 'morgen' van het moment van ophalen; zonder deze vernieuwing
    bevat coordinator.data tot 15 min na middernacht de punten van de nu
    verstreken 'vandaag', en het datumfilter in morgen_prognose laat die
    vallen — precies in het EPEX-gat waarin de prognose nodig is."""
    coordinator = VoorspellingCoordinator(hass, entry)
    async_add_entities([VoorspellingSensor(coordinator)])
    await coordinator.async_refresh()

    unsub = async_track_time_change(
        hass, lambda _now: coordinator.async_request_refresh(), hour=0,
        minute=0, second=0)
    entry.async_on_unload(unsub)
