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
               / "custom_components" / "energyprijs" / "shadow" / "shadow.yaml")


async def _setup_shadow(hass):
    from homeassistant.setup import async_setup_component
    from datetime import datetime, timedelta, timezone
    pkg = yaml.safe_load(SHADOW_PATH.read_text(encoding="utf-8"))
    assert await async_setup_component(hass, "input_number", {"input_number": pkg["input_number"]})
    assert await async_setup_component(hass, "template", {"template": pkg["template"]})
    # sun.sun zaaien na setup: zonvenster dekt de test-data rond 'nu'
    now = datetime.now(timezone.utc)
    hass.states.async_set("sun.sun", "above_horizon", {
        "next_rising": (now - timedelta(hours=1)).isoformat(),
        "next_setting": (now + timedelta(hours=12)).isoformat(),
    })
    # dummy daglijst vóór block_till_done: templates renderen met correct venster
    hass.states.async_set("sensor.stroomprijs_daglijst", "12:00", {"vandaag": [], "morgen": []})
    await hass.async_block_till_done()
    # forceer één herberekening van alle templates (state-trigger op sun.sun)
    hass.states.async_set("sun.sun", "below_horizon", {
        "next_rising": (now - timedelta(hours=1)).isoformat(),
        "next_setting": (now + timedelta(hours=12)).isoformat(),
    })
    await hass.async_block_till_done()
    hass.states.async_set("sun.sun", "above_horizon", {
        "next_rising": (now - timedelta(hours=1)).isoformat(),
        "next_setting": (now + timedelta(hours=12)).isoformat(),
    })
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


def _daglijst_voortgang(in_lagere, in_dure, uit_lagere, uit_dure):
    """Daglijst vanaf NU: 2 kwartieren goedkoop (zon komt binnen), 2 duur."""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    out = []
    for i, (p_in, p_uit) in enumerate([(in_lagere, uit_lagere), (in_lagere, uit_lagere),
                                       (in_dure, uit_dure), (in_dure, uit_dure)]):
        t = (now - timedelta(seconds=7.5) + timedelta(minutes=15 * i)).isoformat()
        out.append({"t": t, "p": 0.2, "in": p_in, "uit": p_uit})
    return out


def _daglijst_piek_met_pv(in_piek, uit_piek, in_pv, uit_pv):
    """Kwartier 1 = het huidige kwartier (avondpiek, daar verkopen we);
    kwartier 2 = straks binnen het zonvenster (goedkoop PV-herlaadmoment)."""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    return [
        {"t": (now - timedelta(seconds=7.5)).isoformat(), "p": 0.2, "in": in_piek, "uit": uit_piek},
        {"t": (now + timedelta(minutes=14)).isoformat(), "p": 0.2, "in": in_pv, "uit": uit_pv},
    ]


async def _trig(hass, soc=50, val="50"):
    """Zet SOC + een trigger-entiteit → template herberekent; wacht tot gesetteld.
    soc is expliciet om stale states in de test te voorkomen."""
    hass.states.async_set("sensor.accu_percentage", str(soc), {"unit_of_measurement": "%"})
    await hass.async_block_till_done()
    # v1.5.2: de log-automation schrijft input_text.shadow_vorige_status na elke
    # statuswijziging; de template-status-sensor leest die via states() en
    # triggert op de write → de status herberekent met de nieuwe prev. In de
    # e2e-fixtures is die write een state-set; hier gewoon even wachten tot
    # het settled (anders ziet de status de oude prev nog).
    await hass.async_block_till_done()
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
        # state-waarde per kwartier laten tikken (net als de echte template-sensor met
        # strftime), dus elke zet is gegarandeerd een state-change voor alle templates.
        from datetime import datetime as _dt, timedelta as _td
        kq = 0
        while True:
            kq += 1
            val = (_dt.now() - _td(seconds=kq)).strftime("%H:%M:%S")
            prev = hass.states.get("sensor.stroomprijs_daglijst")
            if prev is not None and val == prev.state:
                continue
            hass.states.async_set("sensor.stroomprijs_daglijst", val,
                                  {"vandaag": daglijst, "morgen": []})
            await hass.async_block_till_done()
            break

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
    await zet(_daglijst_piek_met_pv(0.40, 0.30, 0.30, 0.05))
    await _trig(hass, 80)
    st = hass.states.get("sensor.shadow_status")
    assert st.state == "COMFORT", f"avondpiek boven eis moet verkopen, got {st.state}"

    # 3) te vol maar verkoop loont niet → ruimtetak: SPAAR (ontladen naar huis)
    await zet(_daglijst_attr(0.30, 0.40, 0.28, 0.30))   # uit 0,30 < eis 0,402
    await _trig(hass, 80)
    st = hass.states.get("sensor.shadow_status")
    assert st.state == "SPAAR", f"ruimtegebrek zonder marge → huis-ontlasting, got {st.state}"

    # 3) negatieve uit → curtail binnen COMFORT-label
    await zet(_daglijst_attr(0.30, 0.40, 0.28, -0.02))
    await _trig(hass, 80)
    st = hass.states.get("sensor.shadow_status")
    assert st.state == "COMFORT (curtail)", st.state
    st = hass.states.get("sensor.shadow_status")
    st = hass.states.get("sensor.shadow_status")
    st = hass.states.get("sensor.shadow_status")


async def test_shadow_hysterese_en_kwartierindex(hass):
    """v1.5.2 — de twee anti-knipperingsfixes:
    1. Hysterese: vlakke prijsspel rond de V-grens (in+w+m ≈ V) mag NIET elk
       kwartier LADEN↔NEUTRAAL tikken. Zolang de prijs binnen ±H van de grens
       blijft, blijft de status staan.
    2. Kwartier-index: de daglijst bevat per kwartier één entry (t = start);
       'nu' = laatste entry met t ≤ nu, niet 'entry met t ≤ nu < t+15m'
       (die rendeert LEEG net vóór het kwartierpunt → 15 min unavailable per
       kwartier, en de log-automation telde die overgangen mee).
    """
    await _setup_shadow(hass)
    hass.states.async_set("sensor.vandaag_verwachte_zonnestroom", "0.0")
    hass.states.async_set("sensor.verwachte_opbrengst_morgen", "0.0")
    await hass.async_block_till_done()

    # ── Hysterese: vlakke prijsspel rond V ─────────────────────────────────
    # V = η × top-12 duurste in = 0,83 × 0,40 = 0,332.  w+m = 0,040.
    # LADEN-grens = V − H = 0,332 − 0,005 = 0,327.
    # P1: in_nu = 0,29 → 0,29 + 0,040 = 0,330 > 0,327 → NIET LADEN (NEUTRAAL)
    # P2: in_nu = 0,285 → 0,285 + 0,040 = 0,325 < 0,327 → LADEN
    # P3: in_nu = 0,29 → 0,330 > 0,327 → MAAR prev == 'LADEN' en
    #     0,330 < V + H = 0,337 → blijft LADEN (hysterese-band)
    async def _zet_laden(in_p, uit_p=0.28):
        """Daglijst: 2 kwartieren goedkoop, 2 duur (top-12 = duurste = 0,40)."""
        from datetime import datetime as _dt, timedelta as _td
        now = _dt.now(_dt.now().astimezone().tzinfo)
        daglijst = [
            {"t": (now - _td(minutes=30)).isoformat(), "p": 0.2, "in": in_p, "uit": uit_p},
            {"t": (now - _td(minutes=15)).isoformat(), "p": 0.2, "in": in_p, "uit": uit_p},
            {"t": (now + _td(minutes=15)).isoformat(), "p": 0.2, "in": 0.40, "uit": 0.38},
            {"t": (now + _td(minutes=30)).isoformat(), "p": 0.2, "in": 0.40, "uit": 0.38},
        ]
        kq = 0
        while True:
            kq += 1
            val = (_dt.now() - _td(seconds=kq)).strftime("%H:%M:%S")
            prev = hass.states.get("sensor.stroomprijs_daglijst")
            if prev is not None and val == prev.state:
                continue
            hass.states.async_set("sensor.stroomprijs_daglijst", val,
                                  {"vandaag": daglijst, "morgen": []})
            await hass.async_block_till_done()
            break

    # P1: in_nu = 0,29 → NEUTRAAL (nog net boven V−H)
    await _zet_laden(0.29)
    await _trig(hass, 50)
    st = hass.states.get("sensor.shadow_status")
    assert st.state == "NEUTRAAL", f"verwacht NEUTRAAL, got {st.state}"

    # P2: in_nu = 0,285 → LADEN (onder V−H)
    await _zet_laden(0.285)
    await _trig(hass, 50)
    st = hass.states.get("sensor.shadow_status")
    assert st.state == "LADEN", f"verwacht LADEN, got {st.state}"
    # P3: in_nu = 0,29 → 0,330 > V−H = 0,327 → ZONDER hysterese zou dit
    # NEUTRAAL zijn, MAAR prev == 'LADEN' en 0,330 < V + H = 0,337 → blijft LADEN
    # (in productie zet de log-automation prev na elke overgang; hier
    # emuleren we die eenmalig, anders leest de sensor prev=''.)
    hass.states.async_set("input_text.shadow_vorige_status", "LADEN")
    await hass.async_block_till_done()
    await _zet_laden(0.29)
    await _trig(hass, 50)
    st = hass.states.get("sensor.shadow_status")
    assert st.state == "LADEN", (
        f"hysterese faalt: 0,330 zit binnen ±H rond V=0,332, "
        f"moet LADEN blijven, got {st.state}")

    # P4: in_nu = 0,34 → 0,34 + 0,040 = 0,38 > V + H = 0,337 → NU wél uit LADEN
    await _zet_laden(0.34)
    await _trig(hass, 50)
    st = hass.states.get("sensor.shadow_status")
    assert st.state in ("NEUTRAAL", "OP HET NET"), (
        f"0,38 > V+H moet uit LADEN, got {st.state}")

    # ── Kwartier-index: 'nu' = laatste entry met t ≤ nu ────────────────────
    # Oude index (t ≤ nu < t+15m): bij nu = t+14m zou de entry nog matchen;
    # bij nu = t+15m niet (leeg → unavailable). Nieuwe index (t ≤ nu):
    # altijd de laatste entry die al begonnen is.
    from datetime import datetime as _dt, timedelta as _td
    now = _dt.now(_dt.now().astimezone().tzinfo)
    # Entry die 20 min geleden begon, dus al 5 min voorbij zijn start:
    daglijst = [
        {"t": (now - _td(minutes=20)).isoformat(), "p": 0.2, "in": 0.25, "uit": 0.24},
        {"t": (now - _td(minutes=5)).isoformat(), "p": 0.2, "in": 0.26, "uit": 0.25},
        {"t": (now + _td(minutes=10)).isoformat(), "p": 0.2, "in": 0.40, "uit": 0.38},
    ]
    val = now.strftime("%H:%M:%S")
    prev = hass.states.get("sensor.stroomprijs_daglijst")
    if prev is not None and val == prev.state:
        val = (now - _td(seconds=1)).strftime("%H:%M:%S")
    hass.states.async_set("sensor.stroomprijs_daglijst", val,
                          {"vandaag": daglijst, "morgen": []})
    await hass.async_block_till_done()
    await _trig(hass, 50)
    st = hass.states.get("sensor.shadow_status")
    # Nieuwe index: nu = laatste entry met t ≤ nu = de -5m entry (in=0,26).
    # Oude index: -5m entry is nu 5 min geleden begonnen, dus t+15m > nu nog
    # niet verstreken → zou óók matchen, maar de -20m entry niet meer.
    # Het cruciale geval is net ná het kwartierpunt (nu = t+14m), waar de
    # oude index LEEG rendeert. Hier testen we dat de sensor WEL een waarde
    # heeft (niet 'unavailable') en die op de juiste in_nu duidt.
    assert st.state not in ("unavailable", "unknown"), (
        f"kwartier-index: sensor mag niet unavailable zijn, got {st.state}")
    in_nu = st.attributes.get("in_nu")
    assert in_nu == 0.26, f"verwacht in_nu=0.26 (laatste entry met t ≤ nu), got {in_nu}"


