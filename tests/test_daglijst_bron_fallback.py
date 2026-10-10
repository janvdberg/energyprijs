"""E2E (v1.5.3): de daglijst pakt de EERSTE bron met een levende daglijst.

Jan (10 okt '26, 2 u): "we hebben nog geen prijzen voor morgen terwijl de
prijzen al wél bekend zijn." Oorzaak: de daglijst las uitsluitend van
EnerPrice; die had de D+1-prijzen om die tijd nog niet. Nu: vaste volgorde
EnerPrice → Nord Pool → EnergyZero, eerste die iets heeft levert de daglijst
(attributes.bron); de andere bronnen dienen als verifiëring via de
momentprijs-kruiscontrole (bestaat al) en de 15:15-melding (noem de bron).
"""
from pathlib import Path

import yaml

PKG_PATH = (Path(__file__).resolve().parents[1]
            / "custom_components" / "energyprijs" / "package.yaml")


def _prijslijst(t0, prijs, n=4):
    """n kwartieren van t0 (ISO-string) met vaste prijs."""
    from datetime import datetime, timedelta, timezone
    d = datetime.fromisoformat(t0)
    out = []
    for i in range(n):
        out.append({"time": (d + timedelta(minutes=15 * i)).isoformat(),
                    "price": prijs})
    return out


async def _setup_daglijst(hass):
    from homeassistant.setup import async_setup_component
    from datetime import datetime, timedelta, timezone
    pkg = yaml.safe_load(PKG_PATH.read_text(encoding="utf-8"))
    # de daglijst-sensor uit het package laden (triggers-blok)
    blok = None
    for item in pkg["template"]:
        if "sensor" in item:
            for s in item["sensor"]:
                if s.get("unique_id") == "stroomprijs_daglijst":
                    blok = [s]
    assert blok is not None, "stroomprijs_daglijst niet gevonden in package.yaml"
    # De drie bron-sensoren: één template-sensor (EnerPrice, zodat we hem
    # via hass.states mogen schrijven met eigen attributes) + twee
    # placeholder-templates voor de id's Nord Pool / EnergyZero — HA
    # slaat handmatige states anders weg op template-gereserveerde id's.
    assert await async_setup_component(hass, "template", {
        "template": [
            {"sensor": [{"name": "Prijzen bron Enerprice",
                         "unique_id": "prijzen_bron_enerprice",
                         "state": "0.20"}]},
            {"sensor": [{"name": "Prijzen bron Nordpool",
                         "unique_id": "prijzen_bron_nordpool",
                         "state": "0.20"},
                        {"name": "Prijzen bron Energyzero",
                         "unique_id": "prijzen_bron_energyzero",
                         "state": "0.20"}]},
            {"sensor": blok},
        ]})
    # contract-helpers zaaien (worden door de formule gelezen)
    assert await async_setup_component(hass, "input_number", {
        "input_number": pkg["input_number"]})
    assert await async_setup_component(hass, "input_boolean", {
        "input_boolean": pkg["input_boolean"]})
    now = datetime.now(timezone.utc)
    t0 = (now - timedelta(minutes=30)).isoformat()
    _zaai(hass, "sensor.prijzen_bron_enerprice", t0, now)
    _zaai(hass, "sensor.prijzen_bron_nordpool", t0, now)
    _zaai(hass, "sensor.prijzen_bron_energyzero", t0, now)
    # één state-tik op de daglijst zelf → template herberekent
    hass.states.async_set("sensor.stroomprijs_daglijst", "0.20",
                          {"vandaag": [], "morgen": []})
    await hass.async_block_till_done()


def _zaai(hass, eid, t0, now):
    """Bron-sensor zaaien met vandaag + morgen (attributes)."""
    from datetime import timedelta, timezone
    hass.states.async_set(eid, "0.20", {
        "prices_today": _prijslijst(t0, 0.20),
        "prices_tomorrow": _prijslijst((now + timedelta(hours=12)).isoformat(), 0.25),
    })


async def _tik_daglijst(hass):
    from datetime import datetime, timedelta, timezone
    kq = 0
    while True:
        kq += 1
        val = (datetime.now(timezone.utc) - timedelta(seconds=kq)).strftime("%H:%M:%S")
        prev = hass.states.get("sensor.stroomprijs_daglijst")
        if prev is not None and val == prev.state:
            continue
        attrs = prev.attributes if prev else {"vandaag": [], "morgen": []}
        # de bron-sensor schrijven (triggert de template herberekening) +
        # de daglijst-state zelf laten tikken
        e = hass.states.get("sensor.prijzen_bron_enerprice")
        if e is not None:
            hass.states.async_set(e.entity_id, e.state, dict(e.attributes))
        await hass.async_block_till_done()
        hass.states.async_set("sensor.stroomprijs_daglijst", val, attrs)
        await hass.async_block_till_done()
        return


async def test_daglijst_enerprice_voorrang(hass):
    """Alle drie levend → EnerPrice wint (vaste volgorde)."""
    await _setup_daglijst(hass)
    await _tik_daglijst(hass)
    st = hass.states.get("sensor.stroomprijs_daglijst")
    assert st is not None
    assert st.attributes.get("bron") == "enerprice", st.attributes.get("bron")
    assert len(st.attributes.get("morgen") or []) > 0


async def test_daglijst_fallback_nordpool(hass):
    """EnerPrice leeg (geen morgen-prijzen) → Nord Pool levert de daglijst."""
    await _setup_daglijst(hass)
    hass.states.async_set("sensor.prijzen_bron_enerprice", "0.20",
                          {"prices_today": [], "prices_tomorrow": []})
    await hass.async_block_till_done()
    await _tik_daglijst(hass)
    st = hass.states.get("sensor.stroomprijs_daglijst")
    assert st.attributes.get("bron") == "nordpool", st.attributes.get("bron")
    morgen = st.attributes.get("morgen")
    assert morgen is not None and len(morgen) > 0, (
        "morgen moet van Nord Pool komen, got: " + str(morgen)[:80])


async def test_daglijst_fallback_energyzero(hass):
    """EnerPrice én Nord Pool leeg → EnergyZero levert de daglijst."""
    await _setup_daglijst(hass)
    for bron in ("sensor.prijzen_bron_enerprice", "sensor.prijzen_bron_nordpool"):
        hass.states.async_set(bron, "0.20",
                              {"prices_today": [], "prices_tomorrow": []})
    await hass.async_block_till_done()
    await _tik_daglijst(hass)
    st = hass.states.get("sensor.stroomprijs_daglijst")
    assert st.attributes.get("bron") == "energyzero", st.attributes.get("bron")
    morgen = st.attributes.get("morgen")
    assert morgen is not None and len(morgen) > 0, (
        "morgen moet van EnergyZero komen, got: " + str(morgen)[:80])
