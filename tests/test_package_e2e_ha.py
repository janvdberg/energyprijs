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
              "input_number.accu_vermogen_uit_kw",
              "input_text.accu_bron_entity",
              "input_boolean.prijs_saldering_energiebelasting_teruggave"):
        assert hass.states.get(h) is not None, f"{h} ontbreekt in HA!"

    accu_eid = "sensor.energyprijs_accu_percentage"
    st = hass.states.get(accu_eid)
    assert st is not None, "accu-template-sensor niet aangemaakt"

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

    # 6) zelfverwijzing → unavailable, geen lus
    await hass.services.async_call(
        "input_text", "set_value",
        {"entity_id": "input_text.accu_bron_entity", "value": accu_eid},
        blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(accu_eid).state == "unavailable"


async def test_package_template_sensor_luistert_niet_meer_naar_handmatig(hass):
    """Regresie voor punt 3: handmatig-veld is weg; availability hangt alleen van input_text af."""
    tekst = PKG_PATH.read_text(encoding="utf-8")
    assert "accu_handmatig_pct" not in tekst
    # template-blok mag geen state-triggers meer hebben op input_*
    import re
    m = re.search(r"- sensor:\n(?:[^\n]+\n)*?        unique_id: energyprijs_accu_percentage", tekst)
    assert m, "accu-template-blok niet gevonden"
    assert "triggers:" not in tekst[max(0, m.start()-300):m.start()+20]
