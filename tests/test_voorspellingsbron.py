"""E2E (v1.7.0): voorspellingsbron vult 'morgen' in het EPEX-gat.

tussen ±00:00 en ~14:10 zijn de D+1 day-ahead-prijzen van EnerPrice/Nord Pool/
EnergyZero nog onbekend → de morgen-balken waren leeg. Nu: stroomvoorspeller.nl
(CC-BY) prognosis via sensor.prijzen_bron_voorspelling_raw -> ..._voorspelling
vervangt dat gat, INFORMATIEF (nooit shadowPIES). EUR/MWh -> /1000 -> onze
formules; entry-vlag 'v': true markeert prognose; binary_sensor blijft false op
prognose zodat de 15:15-melding doorgaat. Bron offline -> lijst blijft leeg.
"""
import asyncio
import json
from pathlib import Path

import yaml

PKG_PATH = (Path(__file__).resolve().parents[1]
            / "custom_components" / "energyprijs" / "package.yaml")


def _prijslijst(t0, prijs, n=4):
    from datetime import datetime, timedelta
    d = datetime.fromisoformat(t0)
    return [{"time": (d + timedelta(minutes=15 * i)).isoformat(), "price": prijs}
            for i in range(n)]


async def _setup(hass):
    """Package-template laden incl. de twee voorspellings-entities."""
    from homeassistant.setup import async_setup_component
    from datetime import datetime, timedelta, timezone
    pkg = yaml.safe_load(PKG_PATH.read_text(encoding="utf-8"))
    daglijst = None
    for item in pkg["template"]:
        if "sensor" in item:
            for s in item["sensor"]:
                if s.get("unique_id") == "stroomprijs_daglijst":
                    daglijst = [s]
    assert daglijst is not None
    # bron-sensoren als sjabloon (attributes schrijfbaar) + raw-ruimer
    bronnen = [{"sensor": [
        {"name": "Prijzen bron Enerprice", "unique_id": "prijzen_bron_enerprice",
         "state": "0.20"},
        {"name": "Prijzen bron Nordpool", "unique_id": "prijzen_bron_nordpool",
         "state": "0.20"},
        {"name": "Prijzen bron Energyzero", "unique_id": "prijzen_bron_energyzero",
         "state": "0.20"}]}]
    # de echte voorspellings-templates uit het package overnemen
    voorsp = []
    for item in pkg["template"]:
        if "sensor" in item:
            for s in item["sensor"]:
                if s.get("unique_id") in ("prijzen_bron_voorspelling",
                                          "prijzen_bron_voorspelling_raw"):
                    voorsp.append(s)
    assert len(voorsp) == 2, "voorspellings-templates ontbreken in package.yaml"
    bronnen.append({"sensor": voorsp})
    bronnen.append({"sensor": daglijst})
    assert await async_setup_component(hass, "template", {"template": bronnen})
    assert await async_setup_component(hass, "input_number", {
        "input_number": pkg["input_number"]})
    assert await async_setup_component(hass, "input_boolean", {
        "input_boolean": pkg["input_boolean"]})
    now = datetime.now(timezone.utc)
    t0 = (now - timedelta(minutes=30)).isoformat()
    for eid in ("sensor.prijzen_bron_enerprice", "sensor.prijzen_bron_nordpool",
                "sensor.prijzen_bron_energyzero"):
        hass.states.async_set(eid, "0.20", {
            "prices_today": _prijslijst(t0, 0.20),
            "prices_tomorrow": _prijslijst((now + timedelta(hours=12)).isoformat(), 0.25)})
    hass.states.async_set("sensor.stroomprijs_daglijst", "00:00",
                          {"vandaag": [], "morgen": []})
    await hass.async_block_till_done()


async def _tik(hass):
    """Herberekening van de daglijst forceren (state-tik op de bron)."""
    from datetime import datetime, timedelta, timezone
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
        hass.states.async_set("sensor.stroomprijs_daglijst", val, dict(prev.attributes))
        await hass.async_block_till_done()
        return


async def _leeg_alle_echte_bronnen(hass):
    for eid in ("sensor.prijzen_bron_enerprice", "sensor.prijzen_bron_nordpool",
                "sensor.prijzen_bron_energyzero"):
        hass.states.async_set(eid, "0.20", {"prices_today": [], "prices_tomorrow": []})
    await hass.async_block_till_done()


async def test_morgen_leeg_zonder_voorspelling(hass):
    """Alle bronnen leeg (EPEX-gat, geen prognose) → morgen blijft leeg, geen fout."""
    await _setup(hass)
    await _leeg_alle_echte_bronnen(hass)
    await _tik(hass)
    st = hass.states.get("sensor.stroomprijs_daglijst")
    assert st.attributes.get("morgen") == []
    assert st.attributes.get("bron") in (None, "")


async def test_voorspelling_vult_morgen(hass):
    """Prognose available + echte bronnen leeg → morgen gevuld, vlag 'v', bron-label."""
    await _setup(hass)
    tomorrow = "2026-10-22T00:00:00+02:00"
    fc = [{"time": f"2026-10-22T{h:02d}:00:00", "predicted": 100.0 + h}
          for h in range(24)]
    hass.states.async_set("sensor.prijzen_bron_voorspelling_raw", "x",
                          {"forecast": fc})
    await hass.async_block_till_done()
    await _leeg_alle_echte_bronnen(hass)
    await _tik(hass)
    st = hass.states.get("sensor.stroomprijs_daglijst")
    m = st.attributes.get("morgen") or []
    assert len(m) == 24, f"verwacht 24 prognose-uren, got {len(m)}"
    assert all(e.get("v") is True for e in m), "prognose-uren moeten vlag 'v' dragen"
    assert st.attributes.get("bron") in ("", None), \
        "'bron' mag NIET op voorspelling vallen — 15:15-melding moet doorgaan"
    # EUR/MWh -> /1000 -> onze formules: helpers staan in de test op 0 → 'in' == bruto
    p0 = m[0]["p"]
    assert abs(p0 - 0.1) < 1e-9, f"bruto moet 0.100 zijn, got {p0}"
    assert abs(m[0]["in"] - p0) < 1e-9, \
        f"met nul-helpers is all-in gelijk aan bruto, got {m[0]['in']}"


async def test_echte_prijzen_verdringen_prognose(hass):
    """EnerPrice heeft weer morgen-prijzen → voorspelling doet NIET mee, geen 'v'."""
    await _setup(hass)
    fc = [{"time": f"2026-10-22T{h:02d}:00:00", "predicted": 100.0} for h in range(24)]
    hass.states.async_set("sensor.prijzen_bron_voorspelling_raw", "x",
                          {"forecast": fc})
    await hass.async_block_till_done()
    await _tik(hass)
    st = hass.states.get("sensor.stroomprijs_daglijst")
    assert st.attributes.get("bron") == "enerprice"
    m = st.attributes.get("morgen") or []
    assert len(m) > 0 and all(not e.get("v") for e in m), \
        "echte prijzen mogen niet als prognose gemarkeerd zijn"


async def test_morgen_beschikbaar_binary_negeert_prognose(hass):
    """binary_sensor prijzen_morgen_beschikbaar: prognose-only → false (15:15-melding gaat door)."""
    await _setup(hass)
    pkg = yaml.safe_load(PKG_PATH.read_text(encoding="utf-8"))
    b = None
    for item in pkg["template"]:
        if not isinstance(item, dict):
            continue
        for key in ("sensor", "binary_sensor"):
            for s in item.get(key, []) or []:
                if isinstance(s, dict) and s.get("unique_id") == "prijzen_morgen_beschikbaar":
                    b = s
    assert b is not None
    from homeassistant.setup import async_setup_component
    # binary_sensor in DEZELFDE setup-call als de sensor-lijst: aparte calls
    # worden door de component genegeerd (single-instance platform-gedrag).
    ss = []
    for item in pkg["template"]:
        if isinstance(item, dict) and "sensor" in item:
            for s in item["sensor"]:
                if s.get("unique_id") in ("prijzen_bron_voorspelling",
                                          "prijzen_bron_voorspelling_raw",
                                          "stroomprijs_daglijst"):
                    ss.append(s)
    assert len(ss) == 3
    # EEN enkele config-dict met zowel sensor- als binary_sensor-lijst: meerdere
    # template-items in een lijst worden door de component genegeerd na de eerste.
    assert await async_setup_component(
        hass, "template",
        {"template": [{"sensor": ss, "binary_sensor": [b]}]})
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.prijzen_morgen_beschikbaar") is not None, \
        "binary_sensor niet geregistreerd — config-fout?"
    # daglijst moet herberekend worden door de voorspelling-trigger: wacht erop
    for _ in range(40):
        st = hass.states.get("sensor.stroomprijs_daglijst")
        if st.attributes.get("morgen"):
            break
        await asyncio.sleep(0.25)
    fc = [{"time": f"2026-10-22T{h:02d}:00:00", "predicted": 100.0} for h in range(24)]
    hass.states.async_set("sensor.prijzen_bron_voorspelling_raw", "x", {"forecast": fc})
    await hass.async_block_till_done()
    await _leeg_alle_echte_bronnen(hass)
    await _tik(hass)
    bs = hass.states.get("binary_sensor.prijzen_morgen_beschikbaar")
    assert bs is not None and bs.state == "off", \
        "prognose mag niet als 'beschikbaar' tellen"
