"""Voorspelling — stroomvoorspeller.nl prognose-bron (v1.7.0, CC-BY).

Informatieve fallback voor het EPEX day-ahead-gat (±00:00–14:10 CET).
Ophaalt forecast.json, filtreert dag+1 (lokaal), en slaat de punten als
attribute 'prices_tomorrow' op de sensor. State = eerste morgen-prijs
(EUR/kWh).

Geen /tmp, geen shell, geen python_script: directe async HTTP via HA's
eigen clientsession (iot_class: cloud_polling). CC-BY: attributie zit in
het attribute 'licentie'.

Bronformaat (live geverifieerd 20 okt '26):
  root = dict; lijst 'forecasts'; per punt
  {"time": "2026-10-21T00:00:00+02:00", "predicted": 180.92, ...}
  horizon = dag+1 t/m dag+7 (168 punten) → wij kiezen alleen dag+1.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

import aiohttp
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)
import homeassistant.util.dt as dt_util

_LOGGER = logging.getLogger(__name__)

FORECAST_URL = "https://stroomvoorspeller.nl/data/forecast.json"
SCAN_INTERVAL = timedelta(minutes=15)
TIMEOUT = aiohttp.ClientTimeout(total=15)


async def async_fetch_forecast(hass: HomeAssistant) -> list[dict]:
    """Haal forecast.json op, filtreer dag+1, geef [{time, predicted}]."""
    session = async_get_clientsession(hass)
    try:
        async with session.get(
            FORECAST_URL, timeout=TIMEOUT,
            headers={"User-Agent": "Energyprijs/1.7.5 (HA integration)"},
        ) as resp:
            resp.raise_for_status()
            doc = await resp.json()
    except Exception as exc:  # noqa: BLE001 — alle netwerkfouten → lege array
        _LOGGER.debug("energyprijs voorspelling: fetch mislukt: %s", exc)
        return []

    pts = doc.get("forecasts") if isinstance(doc, dict) else None
    if not isinstance(pts, list):
        return []

    zone = dt_util.get_default_time_zone()
    morgen = (dt_util.now() + timedelta(days=1)).date()
    out: list[dict] = []
    for p in pts:
        t = p.get("time")
        v = p.get("predicted")
        if not isinstance(t, str) or not isinstance(v, (int, float)):
            continue
        try:
            dt = datetime.fromisoformat(t)
        except ValueError:
            continue
        if dt.tzinfo is None:
            # onverwacht naïef → bron documenteert lokale tijd (Europe/Amsterdam)
            dt = dt.replace(tzinfo=zone)
        # De bron draagt lokale tijd (Europe/Amsterdam-offset, +02:00 zomertijd).
        # Direct .date() nemen op de offset-bewuste dt geeft de lokale datum.
        if dt.astimezone(zone).date() == morgen:
            out.append({"time": t, "predicted": round(float(v) / 1000, 5)})
    return out


class VoorspellingCoordinator(DataUpdateCoordinator[list[dict]]):
    """Coördineert de 15-min fetch van stroomvoorspeller.nl."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name="energyprijs_voorspelling",
            update_interval=SCAN_INTERVAL,
        )

    async def _async_update_data(self) -> list[dict]:
        """Haal de prognose op; bij uitval → lege lijst (sensor unavailable,
        géén UpdateFailed — een fetch-fout mag de coordinator/setup nooit
        breken)."""
        try:
            return await async_fetch_forecast(self.hass)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.debug("energyprijs voorspelling: fetch mislukt: %s", exc)
            return []


class VoorspellingSensor(CoordinatorEntity, SensorEntity):
    """Sensor.prijzen_bron_voorspelling — dag+1 prognose, CC-BY.

    Erft van SensorEntity (zodat native_value/unit worden gebruikt) en van
    CoordinatorEntity (zodat de 15-min coordinator de data voedt)."""

    _attr_name = "Prijzen bron Voorspelling"
    _attr_unique_id = "prijzen_bron_voorspelling"
    _attr_native_unit_of_measurement = "EUR/kWh"
    _attr_icon = "mdi:weather-cloudy-clock"

    def __init__(self, coordinator: VoorspellingCoordinator) -> None:
        super().__init__(coordinator)

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and bool(self.coordinator.data)

    @property
    def native_value(self):
        data = self.coordinator.data
        return data[0]["predicted"] if data else None

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or []
        return {
            "prices_tomorrow": [
                {"time": p["time"], "price": p["predicted"]}
                for p in data
            ],
            "licentie": "Prognose: stroomvoorspeller.nl (CC-BY)",
            "prices_today": [],
        }
