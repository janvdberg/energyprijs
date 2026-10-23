"""E2E (v1.5.3): de daglijst pakt de EERSTE bron met een levende daglijst.

Jan (10 okt '26, 2 u): "we hebben nog geen prijzen voor morgen terwijl de
prijzen al wél bekend zijn." Oorzaak: de daglijst las uitsluitend van
EnerPrice; die had de D+1-prijzen om die tijd nog niet. Nu: vaste volgorde
EnerPrice → Nord Pool → EnergyZero, eerste die iets heeft levert de daglijst
(attributes.bron); de andere bronnen dienen als verifiëring via de
momentprijs-kruiscontrole (bestaat al) en de 15:15-melding (noem de bron).
"""
from pathlib import Path

import pytest

import yaml

PKG_PATH = (Path(__file__).resolve().parents[1]
            / "custom_components" / "energyprijs" / "package.yaml")


def _prijslijst(t0, prijs, n=1):
    """n kwartieren van t0 (ISO-string) met vaste prijs. n=1 is genoeg
    voor de test (de daglijst-template telt alleen | count > 0)."""
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
    def _prijs_attr(eid):
        return "{{ (states('" + eid + "') | default('', true)).split('|')[0] | float(0) }}"

    def _dag_attr(eid, idx):
        # idx=1 → vandaag, idx=2 → morgen (state = 'prijs|vandaag|morgen')
        return ("{% set parts = (states('" + eid + "') | default('', true)).split('|') %}"
                "{% if parts | count > " + str(idx) + " %}"
                "{{ parts[" + str(idx) + "] | from_json }}"
                "{% else %}[]{% endif %}")

    assert await async_setup_component(hass, "template", {
        "template": [
            {"sensor": [{"name": "Test raw Enerprice", "unique_id": "test_enerprice_raw",
                         "state": "0"}]},
            {"sensor": [{"name": "Prijzen bron Enerprice",
                         "unique_id": "prijzen_bron_enerprice",
                         "availability": "{{ states('sensor.test_enerprice_raw') != '' }}",
                         "state": _prijs_attr(RAW_EP),
                         "attributes": {"prices_today": _dag_attr(RAW_EP, 1),
                                        "prices_tomorrow": _dag_attr(RAW_EP, 2)}}]},
            {"sensor": [{"name": "Prijzen bron Nordpool",
                         "unique_id": "prijzen_bron_nordpool",
                         "availability": "{{ states('sensor.test_nordpool_raw') != '' }}",
                         "state": _prijs_attr(RAW_NP),
                         "attributes": {"prices_today": _dag_attr(RAW_NP, 1),
                                        "prices_tomorrow": _dag_attr(RAW_NP, 2)}}]},
            {"sensor": [{"name": "Prijzen bron Energyzero",
                         "unique_id": "prijzen_bron_energyzero",
                         "availability": "{{ states('sensor.test_energyzero_raw') != '' }}",
                         "state": _prijs_attr(RAW_EZ),
                         "attributes": {"prices_today": _dag_attr(RAW_EZ, 1),
                                        "prices_tomorrow": _dag_attr(RAW_EZ, 2)}}]},
            {"sensor": blok},
        ]})
    # contract-helpers zaaien (worden door de formule gelezen)
    assert await async_setup_component(hass, "input_number", {
        "input_number": pkg["input_number"]})
    assert await async_setup_component(hass, "input_boolean", {
        "input_boolean": pkg["input_boolean"]})
    now = datetime.now(timezone.utc)
    t0 = (now - timedelta(minutes=30)).isoformat()
    _zaai(hass, RAW_EP, t0, now)
    _zaai(hass, RAW_NP, t0, now)
    _zaai(hass, RAW_EZ, t0, now)
    await hass.async_block_till_done()


def _zaai(hass, raw_eid, t0, now):
    """Ruwe entiteit draagt 'prijs|vandaag-json|morgen-json' (n=1 kwartier
    per dag → onder de 255-char limiet). De bron-template split dat op."""
    import json
    from datetime import timedelta, timezone
    vandaag = _prijslijst(t0, 0.20)
    morgen = _prijslijst((now + timedelta(hours=12)).isoformat(), 0.25)
    state = "0.20|" + json.dumps(vandaag) + "|" + json.dumps(morgen)
    assert len(state) <= 255, f"state te lang: {len(state)}"
    hass.states.async_set(raw_eid, state)


RAW_EP = "sensor.test_enerprice_raw"
RAW_NP = "sensor.test_nordpool_raw"
RAW_EZ = "sensor.test_energyzero_raw"
@pytest.fixture(autouse=True)
def expected_lingering_timers():
    """De daglijst-sensor draait op time_pattern (5 min) in productie; in
    de test geeft dat een 'lingering timer' na het test-einde. We accepteren
    die timer (de test zelf is geen productie-simulatie)."""
    return True


async def _tik_daglijst(hass, raw_ids):
    """Dwing een volledige herberekening af via state-wijzigingen op de levende
    ruwe bron-entiteiten (productie-getrouw; nooit handmatig op de
    template-entity schrijven — dat blokkeert async_track_template_result)."""
    for rid in raw_ids:
        e = hass.states.get(rid)
        if e is None:
            continue
        # kort veranderen + terugzetten → state_changed op beide momenten;
        # de bron-templates split de state op en de daglijst-template
        # volgt de bron-template via zijn state_changed-trigger.
        cur = e.state
        # een whitespace aan het einde toevoegen + weer verwijderen
        # (verandert de state → triggert de template)
        hass.states.async_set(rid, cur + " ")
        await hass.async_block_till_done()
        hass.states.async_set(rid, cur)
        await hass.async_block_till_done()


async def test_daglijst_enerprice_voorrang(hass):
    """Alle drie levend → EnerPrice wint (vaste volgorde)."""
    await _setup_daglijst(hass)
    await _tik_daglijst(hass, [RAW_EP, RAW_NP, RAW_EZ])
    st = hass.states.get("sensor.stroomprijs_daglijst")
    assert st is not None
    assert st.attributes.get("bron") == "enerprice", st.attributes.get("bron")
    assert len(st.attributes.get("morgen") or []) > 0


async def test_daglijst_fallback_nordpool(hass):
    """EnerPrice leeg (geen dagprijzen) → Nord Pool levert de daglijst.

    v1.7.0-correctie: 'bron' kiest op prices_TODAY (vaste volgorde), dus het
    scenario zet EnerPrice op een lege VANDAAG-lijst; morgen blijft bij
    NordPool. De assertion was onterecht geschrapt tijdens review pass 2 —
    de fallback werkt gewoon, de trigger-volgorchting in de test klopte niet."""
    await _setup_daglijst(hass)
    # EP op lege vandaag-lijst: de dag-attribute van de EP-bron is leeg
    # (prices_today = []) terwijl de prijs zelf nog levert.
    # EP op lege vandaag-lijst: state = 'prijs|[]|morgen'
    import json
    e = hass.states.get(RAW_EP)
    parts = e.state.split("|")
    parts[1] = "[]"
    hass.states.async_set(RAW_EP, "|".join(parts))
    await hass.async_block_till_done()
    await _tik_daglijst(hass, [RAW_NP, RAW_EZ])
    st = hass.states.get("sensor.stroomprijs_daglijst")
    assert st.attributes.get("bron") == "nordpool", st.attributes.get("bron")
    morgen = st.attributes.get("morgen")
    assert morgen is not None and len(morgen) > 0, (
        "morgen moet van Nord Pool komen, got: " + str(morgen)[:80])


async def test_daglijst_fallback_energyzero(hass):
    """EnerPrice én Nord Pool leeg → EnergyZero levert de daglijst."""
    await _setup_daglijst(hass)
    # EP én NP op lege vandaag-lijst.
    for rid in (RAW_EP, RAW_NP):
        e = hass.states.get(rid)
        parts = e.state.split("|")
        parts[1] = "[]"
        hass.states.async_set(rid, "|".join(parts))
    await hass.async_block_till_done()
    await _tik_daglijst(hass, [RAW_EZ])
    st = hass.states.get("sensor.stroomprijs_daglijst")
    assert st.attributes.get("bron") == "energyzero", st.attributes.get("bron")
    morgen = st.attributes.get("morgen")
    assert morgen is not None and len(morgen) > 0, (
        "morgen moet van EnergyZero komen, got: " + str(morgen)[:80])
