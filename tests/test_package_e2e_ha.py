"""E2B: package.yaml laden via HA's template-component in een pytest-hass-fixture.

Bewijst wat de PyYAML-tests niet kunnen: HA accepteert het geconsolideerde
package, de accu-snelkoppeling is state-based LIVE (volgt bron-SOC-wijziging
zonder helper-aanraking), zelfverwijzing geeft unavailable, en alle helpers —
inclusief de zes prijshelpers die door de duplicate-key-bug verdwenen — bestaan.
"""
import re
from pathlib import Path

import yaml

PKG_PATH = (Path(__file__).resolve().parents[1]
            / "custom_components" / "energyprijs" / "package.yaml")


async def _setup_pkg(hass):
    from homeassistant.setup import async_setup_component
    pkg = yaml.safe_load(PKG_PATH.read_text(encoding="utf-8"))
    assert await async_setup_component(hass, "template", {"template": pkg["template"]})
    for d in ("input_number", "input_text", "input_boolean"):
        if d in pkg:
            assert await async_setup_component(hass, d, {d: pkg[d]}), d
    await hass.async_block_till_done()
    return pkg


async def test_package_laadt_in_ha_en_accu_snelkoppeling_is_live(hass):
    await _setup_pkg(hass)

    # 1) alle helpers uit HET GEPARSTE package bestaan als entiteit
    for h in ("input_number.prijs_btw", "input_number.prijs_energiebelasting",
              "input_number.prijs_opslag_afname", "input_number.prijs_opslag_levering",
              "input_number.prijs_laad_drempel", "input_number.prijs_afwijkingsdrempel",
              "input_number.accu_capaciteit_kwh", "input_number.accu_vermogen_in_kw",
              "input_number.accu_vermogen_uit_kw", "input_number.accu_reserve_pct",
              "input_text.accu_bron_entity",
              "input_text.pv_bron_vandaag",
              "input_text.pv_bron_morgen",
              "input_boolean.prijs_saldering_energiebelasting_teruggave"):
        assert hass.states.get(h) is not None, f"{h} ontbreekt in HA!"

    accu_eid = "sensor.energyprijs_accu_percentage"
    st = hass.states.get(accu_eid)
    assert st is not None, "accu-template-sensor niet aangemaakt"

    pv_vandaag_eid = "sensor.energyprijs_pv_vandaag"
    pv_morgen_eid = "sensor.energyprijs_pv_morgen"
    assert hass.states.get(pv_vandaag_eid) is not None, "pv-vandaag-sensor ontbreekt"
    assert hass.states.get(pv_morgen_eid) is not None, "pv-morgen-sensor ontbreekt"

    # 2) leeg bronveld → unavailable (attributes tonen we bewust niet: HA verbergt
    #    die voor onbeschikbare template-sensoren — de kaart leest input_text zelf)
    assert st.state == "unavailable", f"lege bron moet unavailable, got {st.state}"

    # 3) bron aanwijzen → live volgen
    hass.states.async_set("sensor.nep_soc", "57", {"unit_of_measurement": "%"})
    await hass.services.async_call(
        "input_text", "set_value",
        {"entity_id": "input_text.accu_bron_entity", "value": "sensor.nep_soc"},
        blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(accu_eid).state == "57"

    # 4) BRON-SELFS verandert (geen helper-wijziging) → sensor beweegt mee.
    #    DIT is punt 4 uit de review: met het oude triggers-blok zou hier 57 blijven staan.
    hass.states.async_set("sensor.nep_soc", "61", {"unit_of_measurement": "%"})
    await hass.async_block_till_done()
    assert hass.states.get(accu_eid).state == "61", "niet live gevolgd!"

    # 5) onbeschikbare bron → unavailable
    hass.states.async_set("sensor.nep_soc", "unavailable")
    await hass.async_block_till_done()
    assert hass.states.get(accu_eid).state == "unavailable"

    # 6) RESERVE-CONTRACT (v1.4.0): accu_reserve_pct × capaciteit → kWh-sensor.
    reserve_eid = "sensor.energyprijs_accu_reserve"
    st_r = hass.states.get(reserve_eid)
    assert st_r is not None, "reserve-template-sensor niet aangemaakt"
    # default-helper staat op 0 (nog niet gezet) → onbruikbare grens → unavailable
    assert st_r.state == "unavailable", f"reserve 0% moet unavailable, got {st_r.state}"
    await hass.services.async_call(
        "input_number", "set_value",
        {"entity_id": "input_number.accu_reserve_pct", "value": 25}, blocking=True)
    await hass.services.async_call(
        "input_number", "set_value",
        {"entity_id": "input_number.accu_capaciteit_kwh", "value": 80}, blocking=True)
    # sensor.accu_percentage heeft hier geen verse waarde (nep_soc is unavailable),
    # maar de contract-sensor zelf ook niet → availability-eis: wél een SOC-bron nodig.
    hass.states.async_set("sensor.nep_soc", "61", {"unit_of_measurement": "%"})
    await hass.services.async_call(
        "input_text", "set_value",
        {"entity_id": "input_text.accu_bron_entity", "value": "sensor.nep_soc"},
        blocking=True)
    await hass.async_block_till_done()
    st_r = hass.states.get(reserve_eid)
    assert st_r.state == "20.0", f"25% van 80 kWh = 20.0, got {st_r.state}"

    # 7) zelfverwijzing → unavailable, geen lus
    await hass.services.async_call(
        "input_text", "set_value",
        {"entity_id": "input_text.accu_bron_entity", "value": accu_eid},
        blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(accu_eid).state == "unavailable"


async def test_package_pv_snelkoppeling_is_live(hass):
    """PV-contract: leeg → unavailable, bron aanwijzen → live volgen, zelfverwijzing → unavailable."""
    await _setup_pkg(hass)

    pv_vandaag_eid = "sensor.energyprijs_pv_vandaag"
    pv_morgen_eid = "sensor.energyprijs_pv_morgen"

    # leeg → unavailable
    assert hass.states.get(pv_vandaag_eid).state == "unavailable"
    assert hass.states.get(pv_morgen_eid).state == "unavailable"

    # bron aanwijzen → waarde volgt live
    hass.states.async_set("sensor.nep_pv_vandaag", "4.2", {"unit_of_measurement": "kWh"})
    hass.states.async_set("sensor.nep_pv_morgen", "3.8", {"unit_of_measurement": "kWh"})
    await hass.services.async_call(
        "input_text", "set_value",
        {"entity_id": "input_text.pv_bron_vandaag", "value": "sensor.nep_pv_vandaag"},
        blocking=True)
    await hass.services.async_call(
        "input_text", "set_value",
        {"entity_id": "input_text.pv_bron_morgen", "value": "sensor.nep_pv_morgen"},
        blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(pv_vandaag_eid).state == "4.2"
    assert hass.states.get(pv_morgen_eid).state == "3.8"

    # bron zelf verandert (geen helper-wijziging) → sensor beweegt mee
    hass.states.async_set("sensor.nep_pv_vandaag", "4.7", {"unit_of_measurement": "kWh"})
    await hass.async_block_till_done()
    assert hass.states.get(pv_vandaag_eid).state == "4.7", "PV-vandaag niet live gevolgd!"

    # zelfverwijzing → unavailable, geen lus
    await hass.services.async_call(
        "input_text", "set_value",
        {"entity_id": "input_text.pv_bron_morgen", "value": pv_morgen_eid},
        blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(pv_morgen_eid).state == "unavailable"


async def test_package_template_sensor_luistert_niet_meer_naar_handmatig(hass):
    """Regresie voor punt 3: handmatig-veld is weg; availability hangt alleen van input_text af."""
    tekst = PKG_PATH.read_text(encoding="utf-8")
    assert "accu_handmatig_pct" not in tekst
    # template-blok mag geen state-triggers meer hebben op input_*
    m = re.search(r"- sensor:\n(?:[^\n]+\n)*?        unique_id: energyprijs_accu_percentage", tekst)
    assert m, "accu-template-blok niet gevonden"
    assert "triggers:" not in tekst[max(0, m.start()-300):m.start()+20]
