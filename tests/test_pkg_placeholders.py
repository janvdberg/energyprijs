"""v1.7.2: de placeholder-bronnen (Nordpool/EnergyZero) moeten een ECHTE lege
LIJST als prices_today/prices_tomorrow attribute dragen — niet de string '[]'.

De string is een sequence van 2 tekens in Jinja ('[]' | count == 2), dus
'| default([], true) | count > 0' ging waar → de daglijst zag 'echte morgen
bestaat' en rendert morgen_prognose als '[]' (symptoom: grijze balken blijven
leeg terwijl de voorspelling-bron 24 punten heeft). Regresie-test: de
geparseerde template-attribute-templates renderen een lege lijst, en de
echte-eid check is lijst-bewust (is sequence + not string).
"""
import re
from pathlib import Path

import yaml

PKG_PATH = (Path(__file__).resolve().parents[1]
            / "custom_components" / "energyprijs" / "package.yaml")


def _bron_blok(tekst, unique_id):
    m = re.search(rf"- name: \"[^\n]*\"\n\s+unique_id: {unique_id}\b(.*?)(?=\n\s+- (?:name|sensor|binary_sensor|triggers):)", tekst, re.S)
    assert m, f"{unique_id} blok niet gevonden"
    return m.group(0)


async def test_placeholders_renderen_lege_lijst(hass):
    """De attribute-templates van Nordpool/EnergyZero renderen een lege lijst."""
    from homeassistant.setup import async_setup_component
    pkg = yaml.safe_load(PKG_PATH.read_text(encoding="utf-8"))
    sensors = []
    for item in pkg["template"]:
        if isinstance(item, dict) and isinstance(item.get("sensor"), list):
            sensors += [s for s in item["sensor"]
                        if s.get("unique_id") in ("prijzen_bron_nordpool",
                                                  "prijzen_bron_energyzero")]
    sensors_to_load = sensors
    assert await async_setup_component(hass, "template", {"template": {"sensor": sensors_to_load}})
    # de placeholder-bronnen zijn beschikbaar zodra hun core-sensor iets heeft
    hass.states.async_set("sensor.nord_pool_nl_current_price", "0.30")
    hass.states.async_set("sensor.energyzero_today_energy_current_hour_price", "0.363")
    await hass.async_block_till_done()

    np_ = hass.states.get("sensor.prijzen_bron_nordpool")
    ez = hass.states.get("sensor.prijzen_bron_energyzero")
    for st, naam in ((np_, "nordpool"), (ez, "energyzero")):
        assert st is not None, f"{naam} staat er niet"
        for attr in ("prices_today", "prices_tomorrow"):
            v = st.attributes.get(attr)
            assert isinstance(v, list), f"{naam}.{attr} is {type(v).__name__}, niet list: {v!r}"
            assert v == [], f"{naam}.{attr} is niet leeg: {v!r}"


def test_placeholders_geen_string_lijst_in_package():
    """Statische check: geen attribute meer als de STRING '[]' gedefinieerd."""
    tekst = PKG_PATH.read_text(encoding="utf-8")
    for naam in ("nordpool", "energyzero"):
        blok = _bron_blok(tekst, f"prijzen_bron_{naam}")
        assert 'prices_today: "[]" ' not in blok and 'prices_today: "[]"' not in blok, f"{naam}: prices_today is nog een string"
        assert 'prices_tomorrow: "[]"' not in blok, f"{naam}: prices_tomorrow is nog een string"


def test_echte_eid_check_is_lijst_bewust():
    """De echte-morgen check moet 'is sequence and not string' bevatten."""
    tekst = PKG_PATH.read_text(encoding="utf-8")
    assert "pt is sequence and pt is not string and pt | count > 0" in tekst, \
        "echte-eid check is niet lijst-bewust (v1.7.2-guard mist)"
