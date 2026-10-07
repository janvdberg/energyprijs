"""E2E: het SHADOW-package (energyprijs_shadow.yaml) laden via HA's eigen
template-component en de zes beslis-sensoren nameten met gekende prijzen.

Bewijst wat een YAML-pars test niet kan: HA accepteert het package, de
formules uit stroomhandel_tactiek.md (revisie 3) rekenen correct, en de vijf
statuslabels verschijnen zoals bedoeld — inclusief de ruimtetak (SPAAR bij te
vol voor aankomende zon) en curtail (COMFORT bij negatieve uit).
"""
from pathlib import Path

import yaml

SHADOW_PATH = (Path(__file__).resolve().parents[1]
               / "shadow" / "energyprijs_shadow.yaml")


async def _setup_shadow(hass):
    from homeassistant.setup import async_setup_component
    pkg = yaml.safe_load(SHADOW_PATH.read_text(encoding="utf-26" if False else "utf-8"))
    assert await async_setup_component(hass, "input_number", {"input_number": pkg["input_number"]})
    assert await async_setup_component(hass, "template", {"template": pkg["template"]})
    await hass.async_block_till_done()
    return pkg


def _daglijst_attr(in_lagere, in_dure, uit_lagere, uit_dure):
    """Maak een daglijst-attributes dict van 4 kwartieren: 2 goedkoop nu, 2 duur straks."""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    out = []
    for i, (p_in, p_uit) in enumerate([(in_lagere, uit_lagere), (in_lagere, uit_lagere),
                                       (in_dure, uit_dure), (in_dure, uit_dure)]):
        t = (now - timedelta(minutes=30) + timedelta(minutes=15 * i)).isoformat()
        out.append({"t": t, "p": 0.2, "in": p_in, "uit": p_uit})
    return out


async def _trig(hass, soc=50, val="50"):
    """Zet SOC + een trigger-entiteit → template herberekent; wacht tot gesetteld.
    soc is expliciet om stale states in de test te voorkomen."""
    hass.states.async_set("sensor.accu_percentage", str(soc), {"unit_of_measurement": "%"})
    await hass.async_block_till_done()


async def test_shadow_helpers_en_sensoren_bestaan(hass):
    await _setup_shadow(hass)
    for h in ("input_number.shadow_eta", "input_number.shadow_w", "input_number.shadow_m",
              "input_number.shadow_n_top", "input_number.shadow_capaciteit",
              "input_number.shadow_soc_min"):
        assert hass.states.get(h) is not None, f"{h} ontbreekt"
    for s in ("sensor.shadow_doel_soc", "sensor.shadow_v_waarde_opgeslagen_kwh", "sensor.shadow_herlaadkosten",
              "sensor.shadow_verkoop_eis", "sensor.shadow_ruimtegebrek_r", "sensor.shadow_status"):
        assert hass.states.get(s) is not None, f"{s} ontbreekt"
    # startwaarden = tactiek-revisie 3
    assert float(hass.states.get("input_number.shadow_eta").state) == 0.83
    assert float(hass.states.get("input_number.shadow_capaciteit").state) == 92.0


async def test_shadow_doel_soc_rekenaar(hass):
    """S = 18 + 17 = 35 kWh op C=92 → doel-SOC = 100 − 35/92·100 ≈ 61,9%."""
    await _setup_shadow(hass)
    hass.states.async_set("sensor.vandaag_verwachte_zonnestroom", "18.0")
    hass.states.async_set("sensor.verwachte_opbrengst_morgen", "17.0")
    await _trig(hass, 55)
    await _trig(hass)
    st = hass.states.get("sensor.shadow_doel_soc")
    assert st is not None and st.state != "unavailable", st
    assert abs(float(st.state) - 61.9) < 0.6, st.state


async def test_shadow_beslissingen_met_gekende_prijzen(hass):
    """Vier scenario's door één daglijst te simuleren (alleen vandaag, morgen leeg)."""
    await _setup_shadow(hass)
    hass.states.async_set("sensor.vandaag_verwachte_zonnestroom", "0.0")
    hass.states.async_set("sensor.verwachte_opbrengst_morgen", "0.0")
    hass.states.async_set("sensor.accu_percentage", "50", {"unit_of_measurement": "%"})
    await hass.async_block_till_done()

    async def zet(daglijst):
        hass.states.async_set("sensor.stroomprijs_daglijst", "12:00", {"vandaag": daglijst, "morgen": []})
        await hass.async_block_till_done()

    # 1) normale spread: in 0,30→0,40; uit 0,28→0,38; eis ≈ herlaad(0,30)/0,83+0,04 = 0,402
    #    hoogste uit 0,38 < eis → geen COMFORT; R = 50−100 = −50 → geen SPAAR;
    #    V = 0,83×top-duurste(0,40)=0,332; in_nu=0,30 + w+m=0,34 > V → NEUTRAAL/OP HET NET
    await zet(_daglijst_attr(0.30, 0.40, 0.28, 0.38))
    await _trig(hass, 50)
    st = hass.states.get("sensor.shadow_status")
    assert st.state in ("NEUTRAAL", "OP HET NET"), st.state

    # 2) te vol voor aankomende zon (S=40 → doel 56,5; SOC 80 → R=23,5) en PV-herlaad
    #    goedkoop (middag-uit 0,05 → pv_eis ≈ 0,096) → avondpiek 0,30 > pv_eis → COMFORT
    hass.states.async_set("sensor.vandaag_verwachte_zonnestroom", "40.0")
    await _trig(hass, 80)   # doel-SOC = 100−40/92·100 ≈ 56,5 → R = 80−56,5 ≈ 23,5
    await zet(_daglijst_attr(0.30, 0.40, 0.05, 0.30))
    await _trig(hass, 80)
    st = hass.states.get("sensor.shadow_status")
    assert st.state == "COMFORT", f"avondpiek boven eis moet verkopen, got {st.state}"

    # 3) te vol maar verkoop loont niet → ruimtetak: SPAAR (ontladen naar huis)
    await zet(_daglijst_attr(0.30, 0.40, 0.28, 0.30))   # uit 0,30 < eis 0,402
    await _trig(hass, 80)
    st = hass.states.get("sensor.shadow_status")
    assert st.state == "SPAAR", f"ruimtegebrek zonder marge → huis-ontlasting, got {st.state}"

    # 4) negatieve uit → curtail binnen COMFORT-label
    await zet(_daglijst_attr(0.30, 0.40, 0.28, -0.02))
    await _trig(hass, 80)
    st = hass.states.get("sensor.shadow_status")
    assert st.state == "COMFORT (curtail)", st.state
