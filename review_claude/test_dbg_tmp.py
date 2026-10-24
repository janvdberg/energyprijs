"""Eendaagse debug: scenario-4-staten dumpen."""
import pytest
from tests.test_shadow_package import _setup_shadow, _zet_daglijst, _daglijst_attr, _trig

pytestmark = pytest.mark.asyncio


async def test_dbg_scenario4(hass):
    await _setup_shadow(hass)
    hass.states.async_set("input_number.shadow_soc_min", "20")
    hass.states.async_set("sensor.vandaag_verwachte_zonnestroom", "40.0")
    await _trig(hass, 12)
    # scenario 1-3 overdoen als de test
    await _zet_daglijst(hass, _daglijst_attr(0.30, 0.40, 0.28, -0.02))
    await _trig(hass, 12)
    # scenario 4 exact zoals in de test
    hass.states.async_set("input_number.shadow_w", "0")
    hass.states.async_set("input_number.shadow_m", "0")
    hass.states.async_set("input_number.shadow_eta", "1")
    await hass.async_block_till_done()
    await _zet_daglijst(hass, _daglijst_attr(0.05, 0.05, 0.30, 0.30, dal=0.01))
    await _trig(hass, 12)
    for eid in ["sensor.shadow_status", "sensor.shadow_v_waarde_opgeslagen_kwh",
                "sensor.shadow_verkoop_eis", "sensor.shadow_herlaadkosten",
                "sensor.shadow_ruimtegebrek_r", "input_text.shadow_status_vorige"]:
        st = hass.states.get(eid)
        print(f"DBG {eid} = {st.state if st else None}")
    for eid in ["input_number.rendement_laad_pct", "input_number.rendement_ontlaad_pct",
                "input_number.shadow_eta", "input_number.shadow_w", "input_number.shadow_m",
                "input_number.shadow_hysteresis", "input_number.shadow_n_top"]:
        st = hass.states.get(eid)
        print(f"DBG {eid} = {st.state if st else 'BESTAAT NIET'}")
