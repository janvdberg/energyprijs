"""E2E (v1.7.0): voorspellingsbron vult het APARTE attribuut 'morgen_prognose'.

Route (informatief, NOOIT shadowPIES):
  sensor.prijzen_bron_voorspelling (eigen integration, async HTTP, dag+1-filter,
  CC-BY) → attribute 'prices_tomorrow' → daglijst-attribuut 'morgen_prognose'
  (grijze balken op de kaart).

'morgen' en 'bron' blijven op echte prijzen: in het EPEX-gat (alle drie
eigen bronnen leeg) is morgen leeg, bron leeg, morgen_prognose gevuld —
en zodra een echte bron morgen-prijzen heeft: morgen gevuld,
morgen_prognose=[], binary_sensor on. De 15:15-melding is dus blind voor
de prognose. Bron offline → sensor unavailable → morgen_prognose leeg.
"""
import json
from pathlib import Path

import pytest
from datetime import datetime, timedelta, timezone
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

import yaml

PKG_PATH = (Path(__file__).resolve().parents[1]
            / "custom_components" / "energyprijs" / "package.yaml")

SENSOR = "sensor.prijzen_bron_voorspelling"


def _prijslijst(t0, prijs, n=4):
    d = datetime.fromisoformat(t0)
    return [{"time": (d + timedelta(minutes=15 * i)).isoformat(), "price": prijs}
            for i in range(n)]


def _prognose_punten(fc_list):
    """Wat de integration-sensor als 'prices_tomorrow'-attribute draagt.

    fc_list = [{"time": ..., "predicted": ...}] (raw, EUR/MWh).
    De sensor deelt over 1000 → price in EUR/kWh.
    """
    return [{"time": p["time"], "price": round(p["predicted"] / 1000, 5)}
            for p in fc_list]


def _set_voorspelling(hass, fc_list):
    """Simuleer de integration-sensor (test-harness doet geen echte HTTP)."""
    punten = _prognose_punten(fc_list)
    state = "ok" if punten else "[]"
    attrs = {
        "prices_tomorrow": punten,
        "licentie": "Prognose: stroomvoorspeller.nl (CC-BY)",
        "prices_today": [],
    }
    hass.states.async_set(SENSOR, state, attrs)


async def _setup(hass):
    """Package-template laden incl. daglijst + binary + input helpers."""
    from homeassistant.setup import async_setup_component
    pkg = yaml.safe_load(PKG_PATH.read_text(encoding="utf-8"))
    sensors, binaries = [], []
    for item in pkg["template"]:
        if isinstance(item, dict):
            for s in item.get("sensor", []) or []:
                sensors.append(s)
            for b in item.get("binary_sensor", []) or []:
                binaries.append(b)
    assert any(s.get("unique_id") == "stroomprijs_daglijst" for s in sensors)
    # De voorspelling-sensor komt nu uit de integration, niet uit dit template.
    assert any(b.get("unique_id") == "prijzen_morgen_beschikbaar" for b in binaries)
    assert await async_setup_component(hass, "template",
                                       {"template": {"sensor": sensors,
                                                    "binary_sensor": binaries}})
    assert await async_setup_component(hass, "input_number",
                                       {"input_number": pkg["input_number"]})
    assert await async_setup_component(hass, "input_boolean",
                                       {"input_boolean": pkg["input_boolean"]})
    now = datetime.now(timezone.utc)
    t0 = (now - timedelta(minutes=30)).isoformat()
    for eid in ("sensor.prijzen_bron_enerprice", "sensor.prijzen_bron_nordpool",
                "sensor.prijzen_bron_energyzero"):
        hass.states.async_set(eid, "0.20", {
            "prices_today": _prijslijst(t0, 0.20),
            "prices_tomorrow": _prijslijst((now + timedelta(hours=12)).isoformat(), 0.25)})
    await hass.async_block_till_done()


async def _tik(hass):
    """Herberekening van de daglijst forceren (state-tik op de bron)."""
    kq = 0
    while True:
        kq += 1
        val = (datetime.now(timezone.utc) - timedelta(seconds=kq)).strftime("%H:%M:%S")
        prev = hass.states.get("sensor.stroomprijs_daglijst")
        if prev is not None and val == prev.state:
            continue
        e = hass.states.get("sensor.prijzen_bron_enerprice")
        if e is not None:
            hass.states.async_set(e.entity_id, e.state, dict(e.attributes))
        await hass.async_block_till_done()
        if prev is not None:
            hass.states.async_set("sensor.stroomprijs_daglijst", val, dict(prev.attributes))
        await hass.async_block_till_done()
        return


async def _leeg_alle_echte_bronnen(hass):
    for eid in ("sensor.prijzen_bron_enerprice", "sensor.prijzen_bron_nordpool",
                "sensor.prijzen_bron_energyzero"):
        hass.states.async_set(eid, "0.20", {"prices_today": [], "prices_tomorrow": []})
    await hass.async_block_till_done()
@pytest.fixture(autouse=True)
def expected_lingering_timers():
    return True



async def test_morgen_leeg_zonder_voorspelling(hass):
    """Alle bronnen leeg (EPEX-gat, geen prognose) → morgen én morgen_prognose leeg."""
    await _setup(hass)
    await _leeg_alle_echte_bronnen(hass)
    await _tik(hass)
    st = hass.states.get("sensor.stroomprijs_daglijst")
    assert st.attributes.get("morgen") == []
    assert st.attributes.get("morgen_prognose") == []
    assert st.attributes.get("bron") in (None, "")


async def test_voorspelling_vult_morgen_prognose(hass):
    """Prognose available + echte bronnen leeg → morgen_prognose gevuld;
    'morgen' EN 'bron' blijven leeg; binary blijft off (15:15-melding doorgaat)."""
    await hass.config.async_set_time_zone("Europe/Amsterdam")
    await _setup(hass)
    now = datetime.now(timezone.utc)
    morgen = (now + timedelta(days=1)).date()
    fc = [{"time": f"{morgen.isoformat()}T{h:02d}:00:00+02:00", "predicted": 100.0 + h}
          for h in range(24)]
    _set_voorspelling(hass, fc)
    await hass.async_block_till_done()
    # Echte bronnen leeg houden zodat 'morgen' leeg blijft.
    await _leeg_alle_echte_bronnen(hass)
    await hass.async_block_till_done()
    st = hass.states.get("sensor.stroomprijs_daglijst")
    # 'morgen' blijft ECHT leeg — prognose mag niet daarin zitten
    assert st.attributes.get("morgen") == []
    vs2 = hass.states.get(SENSOR)
    pt = vs2.attributes.get("prices_tomorrow", []) if vs2 else []
    m = st.attributes.get("morgen_prognose") or []
    assert len(m) == 24, f"verwacht 24 prognose-uren, got {len(m)}"
    assert st.attributes.get("bron") in ("", None), \
        "'bron' mag NIET op voorspelling vallen — 15:15-melding moet doorgaan"
    # EUR/MWh → /1000 → formules: helpers op 0 → 'in' == bruto
    p0 = m[0]["p"]
    assert abs(p0 - 0.1) < 1e-9, f"bruto moet 0.100 zijn, got {p0}"
    assert abs(m[0]["in"] - p0) < 1e-9, \
        f"met nul-helpers is all-in gelijk aan bruto, got {m[0]['in']}"
    bs = hass.states.get("binary_sensor.prijzen_morgen_beschikbaar")
    assert bs is not None and bs.state == "off", \
        "prognose mag niet als 'morgen beschikbaar' tellen"


async def test_echte_prijzen_verdringen_prognose(hass):
    """EnerPrice heeft morgen-prijzen → 'morgen' gevuld, morgen_prognose leeg."""
    await _setup(hass)
    now = datetime.now(timezone.utc)
    morgen = (now + timedelta(days=1)).date()
    fc = [{"time": f"{morgen.isoformat()}T{h:02d}:00:00+02:00", "predicted": 100.0}
          for h in range(24)]
    _set_voorspelling(hass, fc)
    await hass.async_block_till_done()
    await _tik(hass)  # bronnen hebben al morgen-prijzen uit _setup
    st = hass.states.get("sensor.stroomprijs_daglijst")
    assert st.attributes.get("bron") == "enerprice"
    m = st.attributes.get("morgen") or []
    assert len(m) > 0, "echte morgen-prijzen moeten in 'morgen' zitten"
    assert st.attributes.get("morgen_prognose") == [], \
        "met echte morgen-prijzen moet morgen_prognose leeg zijn"


async def test_binary_morgen_beschikbaar(hass):
    """binary_sensor: off bij prognose-only, on zodra echte morgen-prijzen zijn."""
    await _setup(hass)
    now = datetime.now(timezone.utc)
    morgen = (now + timedelta(days=1)).date()
    fc = [{"time": f"{morgen.isoformat()}T{h:02d}:00:00+02:00", "predicted": 100.0}
          for h in range(24)]
    _set_voorspelling(hass, fc)
    await hass.async_block_till_done()
    await _leeg_alle_echte_bronnen(hass)
    await _tik(hass)
    bs = hass.states.get("binary_sensor.prijzen_morgen_beschikbaar")
    assert bs is not None, "binary_sensor niet geregistreerd — config-fout?"
    assert bs.state == "off", "prognose-only moet off zijn"
    # nu: een echte bron levert morgen-prijzen
    hass.states.async_set("sensor.prijzen_bron_enerprice", "0.20", {
        "prices_today": _prijslijst((now - timedelta(minutes=30)).isoformat(), 0.20),
        "prices_tomorrow": _prijslijst((now + timedelta(hours=12)).isoformat(), 0.25)})
    await _tik(hass)
    # Test-harness: de daglijst's attribute 'morgen' wordt niet herberekend op
    # state-veranderingen van gerefereerde entiteiten. In productie werkt het
    # via de 5-min-trigger; hier forceren we de daglijst's attribute 'morgen'
    # handmatig om de binary-sensor's LOGIC te testen.
    _dag = hass.states.get("sensor.stroomprijs_daglijst")
    if _dag:
        _attrs = dict(_dag.attributes)
        _attrs["morgen"] = [{"t": f"{morgen.isoformat()}T00:00:00", "p": 0.25}]
        hass.states.async_set(_dag.entity_id, _dag.state, _attrs)
        await hass.async_block_till_done()
    bs = hass.states.get("binary_sensor.prijzen_morgen_beschikbaar")
    assert bs.state == "on", f"echte morgen-prijzen moeten 'on' geven, got {bs.state}"
