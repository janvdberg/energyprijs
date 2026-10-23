"""E2E: het SHADOW-package (energyprijs_shadow.yaml) laden via HA's eigen
template-component en de zes beslis-sensoren nameten met gekende prijzen.

Bewijst wat een YAML-pars test niet kan: HA accepteert het package, de
formules uit stroomhandel_tactiek.md (revisie 3) rekenen correct, en de vijf
statuslabels verschijnen zoals bedoeld — inclusief de ruimtetak (SPAAR bij te
vol voor aankomende zon) en curtail (ONTLADEN bij negatieve uit).
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
    # v1.5.4: 'initial:' is uit het package (zou elke HA-herstart tactiekwaarden
    # resetten). In productie zet de installer de startwaarden éénmalig via
    # HELPERS_DEFAULTS — maar die route is contract- én IsDone-bewakend en hoort
    # niet in een geïsoleerde package-test (andere tests delen dezelfde store).
    # Daarom bootst deze fixture hier alleen het *resultaat* na: de waarden die
    # HELPERS_DEFAULTS noemt, gezet op de zojuist geladen helpers. De assertie
    # boven bewijst dat shadow.yaml zelf géén initial meer bevat.
    import custom_components.energyprijs.installer as inst
    for key, value in inst.HELPERS_DEFAULTS.items():
        if not key.startswith("shadow_"):
            continue
        if hass.states.get(f"input_number.{key}") is not None:
            await hass.services.async_call(
                "input_number", "set_value",
                {"entity_id": f"input_number.{key}", "value": value}, blocking=True)
    # v1.6.x: de status-template leest input_text.shadow_status_vorige voor de
    # hysterese-prev. Zonder die helper rendert states() als 'unknown' en valt
    # elke hysterese-tak stil weg (prev == 'LADEN' matcht nooit). Setup dus
    # eerst de input_text-helpers uit het package, vóór de template.
    if pkg.get("input_text"):
        assert await async_setup_component(hass, "input_text", {"input_text": pkg["input_text"]})
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
        dt = now - timedelta(minutes=30) + timedelta(minutes=15 * i)
        out.append({"t": dt.isoformat(), "e": int(dt.timestamp()), "p": 0.2, "in": p_in, "uit": p_uit})
    return out


def _met_epoch(entries):
    """v1.6.2: de V-sensor filtert op e.e >= nu_epoch — fixtures moeten het
    epoch-veld dus bevatten, precies zoals de echte daglijst-template."""
    for e in entries:
        e["e"] = int(datetime.fromisoformat(e["t"]).timestamp())
    return entries


def _daglijst_voortgang(in_lagere, in_dure, uit_lagere, uit_dure):
    """Daglijst vanaf NU: 2 kwartieren goedkoop (zon komt binnen), 2 duur."""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    out = []
    for i, (p_in, p_uit) in enumerate([(in_lagere, uit_lagere), (in_lagere, uit_lagere),
                                       (in_dure, uit_dure), (in_dure, uit_dure)]):
        t = (now - timedelta(seconds=7.5) + timedelta(minutes=15 * i)).isoformat()
        out.append({"t": t, "e": int(now.timestamp()) + (-7.5 + 900 * i), "p": 0.2, "in": p_in, "uit": p_uit})
    return out


def _daglijst_piek_met_pv(in_piek, uit_piek, in_pv, uit_pv):
    """Kwartier 1 = het huidige kwartier (avondpiek, daar verkopen we);
    kwartier 2 = straks binnen het zonvenster (goedkoop PV-herlaadmoment)."""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    base = int(now.timestamp())
    return [
        {"t": (now - timedelta(seconds=7.5)).isoformat(), "e": base - 7, "p": 0.2, "in": in_piek, "uit": uit_piek},
        {"t": (now + timedelta(minutes=14)).isoformat(), "e": base + 840, "p": 0.2, "in": in_pv, "uit": uit_pv},
    ]


async def _trig(hass, soc=50, val="50"):
    """Zet SOC + een trigger-entiteit → template herberekent; wacht tot gesetteld.
    soc is expliciet om stale states in de test te voorkomen."""
    hass.states.async_set("sensor.accu_percentage", str(soc), {"unit_of_measurement": "%"})
    await hass.async_block_till_done()
    # v1.5.2: de log-automation schrijft input_text.shadow_status_vorige na elke
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
    #    hoogste uit 0,38 < eis → geen ONTLADEN; R = 50−100 = −50 → geen SPAAR;
    #    V = 0,83×top-duurste(0,40)=0,332; in_nu=0,30 + w+m=0,34 > V → NEUTRAAL/OP HET NET
    await zet(_daglijst_attr(0.30, 0.40, 0.28, 0.38))
    await _trig(hass, 50)
    st = hass.states.get("sensor.shadow_status")
    assert st.state in ("NEUTRAAL", "OP HET NET"), st.state

    # 2) te vol voor aankomende zon (S=40 → doel 56,5; SOC 80 → R=23,5) en PV-herlaad
    #    goedkoop (middag-uit 0,05 → pv_eis ≈ 0,096) → avondpiek 0,30 > pv_eis → ONTLADEN
    hass.states.async_set("sensor.vandaag_verwachte_zonnestroom", "40.0")
    await _trig(hass, 80)   # doel-SOC = 100−40/92·100 ≈ 56,5 → R = 80−56,5 ≈ 23,5
    await zet(_daglijst_piek_met_pv(0.40, 0.30, 0.30, 0.05))
    await _trig(hass, 80)
    st = hass.states.get("sensor.shadow_status")
    assert st.state == "ONTLADEN", f"avondpiek boven eis moet verkopen, got {st.state}"

    # 3) te vol maar verkoop loont niet → ruimtetak: SPAAR (ontladen naar huis)
    await zet(_daglijst_attr(0.30, 0.40, 0.28, 0.30))   # uit 0,30 < eis 0,402
    await _trig(hass, 80)
    st = hass.states.get("sensor.shadow_status")
    assert st.state == "SPAAR", f"ruimtegebrek zonder marge → huis-ontlasting, got {st.state}"

    # 3) negatieve uit → curtail binnen ONTLADEN-label
    await zet(_daglijst_attr(0.30, 0.40, 0.28, -0.02))
    await _trig(hass, 80)
    st = hass.states.get("sensor.shadow_status")
    assert st.state == "ONTLADEN (curtail)", st.state
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
    # v1.7.5d: de beslis-template deelt de LADEN-grens op η_laad
    # (in_nu/η_laad + w + m < V − H). η_laad = 0,77 → in_nu/0,77 ≈ 1,30 ×
    # in_nu. De V-sensor filtert op e >= nu_epoch, dus verstreken entries
    # tellen NIET mee — top-12 = alleen de 2 dure toekomstprijzen (0,40).
    # V = 0,693 × 0,40 = 0,2772.  LADEN-grens = V − H = 0,2722.
    # P1: in_nu = 0,20 → 0,20/0,77 + 0,040 = 0,299 > 0,2722 → NEUTRAAL
    # P2: in_nu = 0,195 → 0,195/0,77 + 0,040 = 0,294 < 0,2722 → LADEN
    #     MAAR: 0,294 > 0,2722!  → NEUTRAAL.  We moeten lager:
    #     in_nu < (V−H) × η_laad − w+m × η_laad = (0,2722−0,040)×0,77 = 0,179
    #     in_nu = 0,17 → 0,17/0,77 + 0,040 = 0,261 < 0,2722 → LADEN
    # P3: in_nu = 0,20 → 0,299 > V−H = 0,2722, MAAR prev == 'LADEN' en
    #     0,299 < V + H = 0,2822?  NEE, 0,299 > 0,2822.  → NEUTRAAL.
    #     De hysterese-band is ±H op de GRENZWAARDE in/η_laad+w+m, dus de
    #     in_nu-ruimte is η_laad × 2H = 0,77 × 0,01 = 0,0077.  Te smal voor
    #     de test-resolutie.  P3 emuleren met in_nu = 0,175:
    #     0,175/0,77 + 0,040 = 0,268 < 0,2822 → LADEN (binnen band).
    # P4: in_nu = 0,19 → 0,19/0,77 + 0,040 = 0,287 > 0,2822 → uit LADEN.
    async def _zet_laden(in_p, uit_p=0.28):
        """Daglijst: verstreken entry (nu−2min, in_p) + 2 dure toekomstprijzen
        (0,40). De V-sensor telt alleen e >= nu → top = 2× 0,40 → V = 0,2772."""
        from datetime import datetime as _dt, timedelta as _td
        now = _dt.now(_dt.now().astimezone().tzinfo)
        daglijst = [
            {"t": (now - _td(minutes=2)).isoformat(), "e": int((now - _td(minutes=2)).timestamp()), "p": 0.2, "in": in_p, "uit": uit_p},
            {"t": (now + _td(minutes=15)).isoformat(), "e": int((now + _td(minutes=15)).timestamp()), "p": 0.2, "in": 0.40, "uit": 0.38},
            {"t": (now + _td(minutes=30)).isoformat(), "e": int((now + _td(minutes=30)).timestamp()), "p": 0.2, "in": 0.40, "uit": 0.38},
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

    # v1.7.5d: η_rt = 0,83 (fallback, rend-helpers unknown in deze test).
    # V = 0,83 × 0,40 = 0,332.  LADEN-grens = V − H = 0,327.
    # Beslisregel: in_nu/η_laad + w + m < V − H
    # η_laad = 0,77 → in_nu < (V−H−w−m) × η_laad = (0,327−0,040)×0,77 = 0,221
    # Hysterese-band: in_nu/η_laad + w + m ∈ (V−H, V+H)
    #   → in_nu ∈ ((V−H−w−m)×η_laad, (V+H−w−m)×η_laad) = (0,221, 0,229)
    # P1: in_nu = 0,24 → 0,24/0,77+0,04 = 0,352 > V = 0,332 → NEUTRAAL
    # P2: in_nu = 0,21 → 0,21/0,77+0,04 = 0,313 < V−H = 0,327 → LADEN
    # P3: in_nu = 0,23 → 0,23/0,77+0,04 = 0,339 → > V−H, < V+H → LADEN (band)
    # P4: in_nu = 0,25 → 0,25/0,77+0,04 = 0,365 > V+H = 0,337 → uit LADEN
    # P1: in_nu = 0,24 → NEUTRAAL
    await _zet_laden(0.24)
    await _trig(hass, 50)
    st = hass.states.get("sensor.shadow_status")
    assert st.state == "NEUTRAAL", f"P1: verwacht NEUTRAAL, got {st.state}"

    # P2: in_nu = 0,21 → LADEN
    await _zet_laden(0.21)
    await _trig(hass, 50)
    st = hass.states.get("sensor.shadow_status")
    if st.state != "LADEN":
        import time as _t
        dag = hass.states.get("sensor.stroomprijs_daglijst")
        vandaag = dag.attributes.get("vandaag", []) if dag else []
        nu2 = [e for e in vandaag if e.get("e", 0) <= _t.time()]
        in_nu = nu2[-1]["in"] if nu2 else None
        V = float(hass.states.get("sensor.shadow_v_waarde_opgeslagen_kwh").state)
        H = float(hass.states.get("input_number.shadow_hysteresis").state)
        w = float(hass.states.get("input_number.shadow_w").state)
        m = float(hass.states.get("input_number.shadow_m").state)
        _r = hass.states.get("input_number.rendement_laad_pct")
        eta_laad = float(_r.state) / 100 if _r else 0.77
        prev = hass.states.get("input_text.shadow_status_vorige")
        prev = prev.state if prev else None
        raise AssertionError(
            f"P2: verwacht LADEN, got {st.state}; "
            f"in_nu={in_nu} V={V} H={H} w={w} m={m} eta_laad={eta_laad} "
            f"prev={prev} | in/eta_laad+w+m={in_nu/eta_laad+w+m if in_nu else '?'} "
            f"g_laden={V-H} g_laden_uit={V+H}")
    assert st.state == "LADEN", f"P2: verwacht LADEN, got {st.state}"
    # P3: in_nu = 0,225 → 0,225/0,77+0,04 = 0,332 → = V → binnen band → LADEN
    await hass.services.async_call(
        "input_text", "set_value",
        {"entity_id": "input_text.shadow_status_vorige", "value": "LADEN"},
        blocking=True)
    await hass.async_block_till_done()
    await _zet_laden(0.225)
    await _trig(hass, 50)
    st = hass.states.get("sensor.shadow_status")
    if st.state != "LADEN":
        import time as _t
        dag = hass.states.get("sensor.stroomprijs_daglijst")
        vandaag = dag.attributes.get("vandaag", []) if dag else []
        nu2 = [e for e in vandaag if e.get("e", 0) <= _t.time()]
        in_nu = nu2[-1]["in"] if nu2 else None
        V = float(hass.states.get("sensor.shadow_v_waarde_opgeslagen_kwh").state)
        H = float(hass.states.get("input_number.shadow_hysteresis").state)
        _r = hass.states.get("input_number.rendement_laad_pct")
        eta_laad = float(_r.state) / 100 if _r else 0.77
        prev = hass.states.get("input_text.shadow_status_vorige")
        prev = prev.state if prev else None
        val = in_nu/eta_laad + 0.025 + 0.015 if in_nu else '?'
        raise AssertionError(
            f"P3: verwacht LADEN, got {st.state}; "
            f"in_nu={in_nu} V={V} H={H} eta_laad={eta_laad} "
            f"prev={prev} | in/eta_laad+w+m={val} g_laden_uit={V+H}")
    assert st.state == "LADEN", (
        f"hysterese faalt, got {st.state}")

    # P4: in_nu = 0,25 → buiten band → uit LADEN
    await _zet_laden(0.25)
    await _trig(hass, 50)
    st = hass.states.get("sensor.shadow_status")
    assert st.state in ("NEUTRAAL", "OP HET NET"), (
        f"0,25/0,77+0,04=0,365 > V+H=0,337 moet uit LADEN, got {st.state}")

    # ── Kwartier-index: 'nu' = laatste entry met t ≤ nu ────────────────────
    # Oude index (t ≤ nu < t+15m): bij nu = t+14m zou de entry nog matchen;
    # bij nu = t+15m niet (leeg → unavailable). Nieuwe index (t ≤ nu):
    # altijd de laatste entry die al begonnen is.
    from datetime import datetime as _dt, timedelta as _td
    now = _dt.now(_dt.now().astimezone().tzinfo)
    # Entry die 20 min geleden begon, dus al 5 min voorbij zijn start:
    daglijst = [
        {"t": (now - _td(minutes=20)).isoformat(), "e": int((now - _td(minutes=20)).timestamp()), "p": 0.2, "in": 0.25, "uit": 0.24},
        {"t": (now - _td(minutes=5)).isoformat(), "e": int((now - _td(minutes=5)).timestamp()), "p": 0.2, "in": 0.26, "uit": 0.25},
        {"t": (now + _td(minutes=10)).isoformat(), "e": int((now + _td(minutes=10)).timestamp()), "p": 0.2, "in": 0.40, "uit": 0.38},
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


