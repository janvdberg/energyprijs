"""E2E v1.7.0: de voorspelling-sensor (stroomvoorspeller.nl) écht getest.

Tot nu toe werd alleen sensor.prijzen_bron_voorspelling gemockt met
hass.states.async_set — en die mock verborg eerder al een bug (review pass 3,
punt 4). Deze test haalt async_fetch_forecast + VoorspellingSensor via de
echte HTTP-mock (aioclient_mock) en controleert state, unit en attributes.

Let op de schaal: de echte bron rapporteert EUR/MWh in ORDINAIRE euro's
(±180 EUR/MWh = ±0,18 EUR/kWh), dus de sensor deelt door 1000.
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.energyprijs.voorspelling import (
    FORECAST_URL,
    VoorspellingSensor,
    VoorspellingCoordinator,
    async_fetch_forecast,
)


def _basis_morgen():
    zone = dt_util.get_default_time_zone()
    return datetime.now(zone).replace(hour=0, minute=0, second=0, microsecond=0) \
        + timedelta(days=1)


def _forecast_doc(n_uur_punt: int = 5) -> dict:
    """Realistisch forecast.json-document: punten vanaf morgen 00:00 lokaal,
    EUR/MWh in gewone euro's (bron-eenheid), veldnamen exact als de API."""
    basis = _basis_morgen()
    pts = []
    for i in range(n_uur_punt):
        t = basis + timedelta(hours=i)
        # 180 + i EUR/MWh → na deling 0,180 / 0,181 ... EUR/kWh
        pts.append({"time": t.isoformat(), "predicted": 180.0 + i})
    return {"forecasts": pts, "tz": "Europe/Amsterdam", "unit": "EUR/MWh"}


async def test_fetch_filtert_morgen_en_rekent_eur_mwh_naar_kwh(hass: HomeAssistant, aioclient_mock):
    """async_fetch_forecast geeft alleen morgen-punten; EUR/MWh → EUR/kWh."""
    doc = _forecast_doc(5)
    aioclient_mock.get(FORECAST_URL, json=doc)
    out = await async_fetch_forecast(hass)
    assert len(out) == 5, f"verwacht 5 punten, got {len(out)}"
    assert out[0]["predicted"] == 0.18, out[0]      # 180 EUR/MWh → 0,18 EUR/kWh
    assert out[4]["predicted"] == 0.184, out[4]     # afgerond op 3 decimalen
    assert aioclient_mock.call_count == 1


async def test_fetch_gooit_andere_dagen_weg(hass: HomeAssistant, aioclient_mock):
    """Punten van vandaag/overmorgen vallen weg — alleen dag+1 blijft."""
    basis = _basis_morgen() - timedelta(days=1)    # vandaag 00:00 lokaal
    doc = {"forecasts": [
        {"time": (basis - timedelta(hours=1)).isoformat(), "predicted": 100.0},  # gisteren
        {"time": basis.isoformat(), "predicted": 120.0},                          # vandaag 00u
        {"time": (basis + timedelta(days=1)).isoformat(), "predicted": 140.0},    # morgen 00u
        {"time": (basis + timedelta(days=2)).isoformat(), "predicted": 160.0},    # overmorgen
    ]}
    aioclient_mock.get(FORECAST_URL, json=doc)
    out = await async_fetch_forecast(hass)
    assert len(out) == 1, f"alleen morgen mag overblijven, got {out}"
    assert out[0]["predicted"] == 0.14


async def test_fetch_netwerkfout_geeft_lege_lijst(hass: HomeAssistant, aioclient_mock):
    """Netwerkfout → lege lijst, geen exception (sensor unavailable)."""
    aioclient_mock.get(FORECAST_URL, exc=ConnectionError("offline"))
    out = await async_fetch_forecast(hass)
    assert out == []


async def test_sensor_state_unit_en_attributes(hass: HomeAssistant, aioclient_mock):
    """Coordinatordraad + sensor: fetch bij refresh, state = eerste prijs,
    unit-attribuut echt aanwezig (review pass 3, punt 1), prices_tomorrow gevuld."""
    doc = _forecast_doc(3)
    aioclient_mock.get(FORECAST_URL, json=doc)

    entry = SimpleNamespace(async_on_unload=lambda cb: None)
    coordinator = VoorspellingCoordinator(hass, entry)
    sensor = VoorspellingSensor(coordinator)
    sensor.entity_id = "sensor.prijzen_bron_voorspelling"
    sensor.hass = hass
    await coordinator.async_refresh()

    assert aioclient_mock.call_count >= 1, "coordinator moet bij refresh fetchen"
    assert sensor.native_value == 0.18, sensor.native_value
    # SensorEntity leest _attr_native_unit_of_measurement — deze test vangt
    # precies die bug: met _attr_unit_of_measurement is dit None.
    assert sensor.unit_of_measurement == "EUR/kWh", sensor.unit_of_measurement
    attrs = sensor.extra_state_attributes
    tomorrow = attrs["prices_tomorrow"]
    assert len(tomorrow) == 3
    assert tomorrow[0]["price"] == 0.18
    assert "CC-BY" in attrs["licentie"]
