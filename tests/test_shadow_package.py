"""E2E: het SHADOW-package (energyprijs_shadow.yaml) laden via HA's eigen
template-component en de zes beslis-sensoren nameten met gekende prijzen.

Bewijst wat een YAML-pars test niet kan: HA accepteert het package, de
formules uit stroomhandel_tactiek.md (revisie 3) rekenen correct, en de vijf
statuslabels verschijnen zoals bedoeld — inclusief de ruimtetak (Doorleveren bij te
vol voor aankomende zon) en curtail (Ontladen bij negatieve uit).
"""
from datetime import datetime
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
    # v1.9.2: de reserve-aware onlaadplanning leest accu_reserve_pct (de enige
    # reserve-waarde van het dashboard) en accu_vermogen_uit_kw — geen shadow_-
    # prefix, dus hier expliciet gezaaid zoals in productie via HELPERS_DEFAULTS.
    # v1.9.2: accu_reserve_pct + accu_vermogen_uit_kw leven in het MAIN package,
    # niet in shadow.yaml. In de geisoleerde shadow-fixture bestaan ze dus niet:
    # set_value faalt er stil op en de templates vallen terug op eigen defaults
    # (flor 20 / P 5). Zaai ze expliciet als state, conform HELPERS_DEFAULTS.
    # v1.9.3: zaai alléén de twee helpers waar de statusketen primary naar kijkt.
    # rendement_laad/ontlaad_pct worden NIET gezaaid: het rendement-contract
    # (v1.5.5) doet has_value() en laat de template dan terugvallen op de
    # noodvallet shadow_eta — de suite-referentie-η (0,83, of 1 in fixtures die
    # dat expliciet zetten). Productie-η (77×90) leeft in de main-suite.
    for _k in ("accu_reserve_pct", "accu_vermogen_uit_kw"):
        hass.states.async_set(f"input_number.{_k}", str(inst.HELPERS_DEFAULTS[_k]))
    # v1.9.3: zaai de verwachte-zonnestroom-sensoren op 0 kWh — dan is doel-SOC
    # 100% en R = SOC−doel overal negatief. Zonder deze zaai is R een restwaarde
    # van eerdere tests in dezelfde store (fixture-deeling!) en kan de Spaar-tak
    # (R > 0) de beslisketen verrassen. Deze test gaat over de PRIJSband; de
    # ruimte-tak moet daarvoor uitgeschakeld zijn.
    for _s in ("sensor.vandaag_verwachte_zonnestroom", "sensor.verwachte_opbrengst_morgen"):
        hass.states.async_set(_s, "0", {"unit_of_measurement": "kWh"})
    # v1.9.3: rendements-helpers bestaan pas als iemand ze zet; de eerste
    # render van de eis-sensor gebeurt bij package-setup met daglijst leeg →
    # unavailable. Een unavailable template-entiteit herberekent HA niet bij
    # latere input-wijzigingen (bewezen in deze testrun), dus zaai η hier vóór
    # de template-setup — exact zoals productie (installer zet HELPERS_DEFAULTS
    # incl. rendement vóórdat het package laadt).
    # v1.9.3: suite-referentie η_rt = 0,83 — expliciet via de noodvallet
    # shadow_eta. In deze geisoleerde fixture bestaan de gemeten
    # rendements-helpers niet (has_value false), dus de template valt terug op
    # shadow_eta en die zetten we hier op de referentiewaarde. Tests die
    # η_rt = 1 nodig hebben (hysterese, neutraal) zetten dat in hun eigen
    # fixture; productionele η (77×90) wordt elders geverifieerd.
    hass.states.async_set("input_number.shadow_eta", "0.83")
    for key, value in inst.HELPERS_DEFAULTS.items():
        if not key.startswith("shadow_"):
            continue
        if hass.states.get(f"input_number.{key}") is not None:
            await hass.services.async_call(
                "input_number", "set_value",
                {"entity_id": f"input_number.{key}", "value": value}, blocking=True)
    # v1.6.x: de status-template leest input_text.shadow_status_vorige voor de
    # hysterese-prev. Zonder die helper rendert states() als 'unknown' en valt
    # elke hysterese-tak stil weg (prev == 'Laden' matcht nooit). Setup dus
    # eerst de input_text-helpers uit het package, vóór de template.
    if pkg.get("input_text"):
        assert await async_setup_component(hass, "input_text", {"input_text": pkg["input_text"]})
    # v1.9.0: de accu-blokkade binary_sensor is genest onder template
    # (pkg['template'][0]['binary_sensor']); er is geen top-level blok meer.
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


def _daglijst_attr(in_lagere, in_dure, uit_lagere, uit_dure, dal=None):
    """Maak een daglijst-attributes dict van 4 kwartieren: 2 goedkoop nu, 2 duur straks.
    `dal`: optioneel extra kwartier met diepere in-prijs (bepaalt V lager dan nu)."""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    out = []
    for i, (p_in, p_uit) in enumerate([(in_lagere, uit_lagere), (in_lagere, uit_lagere),
                                       (in_dure, uit_dure), (in_dure, uit_dure)]):
        dt = now - timedelta(minutes=30) + timedelta(minutes=15 * i)
        out.append({"t": dt.isoformat(), "e": int(dt.timestamp()), "p": 0.2, "in": p_in, "uit": p_uit})
    if dal is not None:
        # verleden-kwartier: de V-sensor filtert op e >= nu_epoch, dus een diepe
        # dal vóór nu drukt V níét — zo blijft V hoog terwijl 'nu' goedkoop is.
        dt = now - timedelta(hours=3)
        out.append({"t": dt.isoformat(), "e": int(dt.timestamp()), "p": 0.2, "in": dal, "uit": dal})
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


async def _zet_daglijst(hass, daglijst):
    """state-waarde per kwartier laten tikken (net als de echte template-sensor
    met strftime), dus elke zet is gegarandeerd een state-change voor alle templates."""
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


async def _trig(hass, soc=50, val="50", herlaad=None, prev=None):
    """Zet SOC + optioneel h (sensor.shadow_herlaadkosten) → templates
    herberekenen; wacht tot gesetteld. soc=None laat de SOC-state met rust
    (voor unavailable-tests).
    let op: een state-set op sensor.shadow_herlaadkosten is NIET
    betrouwbaar — de template herberekent h = min(in) over 24 u na elke
    daglijst-write en overschrijft die set bij de volgende render. Forceer
    inputs (de ladder), nooit deze output. `herlaad` blijft alleen bestaan
    voor tests die de sensor expres unavailable/niet-zet."""
    if herlaad is not None:
        hass.states.async_set("sensor.shadow_herlaadkosten", str(herlaad),
                              {"unit_of_measurement": "€/kWh"})
    if soc is not None:
        hass.states.async_set("sensor.accu_percentage", str(soc), {"unit_of_measurement": "%"})
    await hass.async_block_till_done()
    if prev is not None:
        # v1.9.3: prev via state-set — async_set op input_text triggert hier
        # dezelfde status-render als de productie-log-automation (in deze
        # geisoleerde fixture leeft die automation niet en faalt de
        # service-call stil).
        hass.states.async_set("input_text.shadow_status_vorige", prev)
        await hass.async_block_till_done()
    # v1.5.2: de log-automation schrijft input_text.shadow_status_vorige na elke
    # statuswijziging; de template-status-sensor leest die via states() en
    # triggert op de write → de status herberekent met de nieuwe prev. In de
    # e2e-fixtures is die write een state-set; hier gewoon even wachten tot
    # het settled (anders ziet de status de oude prev nog).
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
        await _zet_daglijst(hass, daglijst)


    # 1) normale spread: in 0,30→0,40; uit 0,28→0,34; eis = herlaad(0,30)/η_rt + w+m
    #    met η = shadow_eta 0,83 → 0,30/0,83 + 0,04 ≈ 0,401.
    #    hoogste uit 0,34 < eis → geen Ontladen; R = 50−100 = −50 → geen Doorleveren;
    #    V = 0,83×top-duurste(0,40)=0,332; in_nu=0,30 + w+m=0,34 > V → Neutraal/Spaar
    await zet(_daglijst_attr(0.30, 0.40, 0.28, 0.34))
    await _trig(hass, 50)
    st = hass.states.get("sensor.shadow_status")
    assert st.state == "Neutraal", (
        f"in_nu+w+m 0,34 > V en uit onder eis → verbruiksband, got {st.state}")

    # 2) te vol voor aankomende zon (S=40 → doel 56,5; SOC 80 → R=23,5) en PV-herlaad
    #    goedkoop (middag-uit 0,05 → pv_eis ≈ 0,096) → avondpiek 0,30 > pv_eis → Ontladen
    hass.states.async_set("sensor.vandaag_verwachte_zonnestroom", "40.0")
    await _trig(hass, 80)   # doel-SOC = 100−40/92·100 ≈ 56,5 → R = 80−56,5 ≈ 23,5
    await zet(_daglijst_piek_met_pv(0.40, 0.30, 0.30, 0.05))
    await _trig(hass, 80)
    st = hass.states.get("sensor.shadow_status")
    assert st.state == "Ontladen", f"avondpiek boven eis moet verkopen, got {st.state}"

    # 3) te vol maar verkoop loont niet → ruimtetak: Doorleveren (ontladen naar huis)
    await zet(_daglijst_attr(0.30, 0.40, 0.28, 0.30))   # uit 0,30 < eis 0,402
    await _trig(hass, 80)
    st = hass.states.get("sensor.shadow_status")
    assert st.state == "Doorleveren", f"ruimtegebrek zonder marge → huis-ontlasting, got {st.state}"

    # 3) negatieve uit → curtail binnen Ontladen-label
    await zet(_daglijst_attr(0.30, 0.40, 0.28, -0.02))
    await _trig(hass, 80)
    st = hass.states.get("sensor.shadow_status")
    assert st.state == "Ontladen (curtail)", st.state


async def test_onder_reserve_model():
    """Het onder_reserve-Jinja-model op zich (v1.8.5): instap pas boven flor+2,
    uit-stap pas bij flor (bandbreedte); onbekende/onbeschikbare SOC =
    geblokkeerd (fail-safe)."""
    from jinja2 import Template
    _FLOR = "20"
    _S = {"sensor.accu_percentage": "12", "input_number.shadow_soc_min": _FLOR}
    tpl = Template(
        "{% set soc_raw = states('sensor.accu_percentage') %}"
        "{% set soc_num = soc_raw | float(-1) %}"
        "{% set soc_ok = soc_raw not in ['unknown', 'unavailable'] and soc_num >= 0 %}"
        "{% set flor = states('input_number.shadow_soc_min') | float(20) %}"
        "{% set in_reserve = (not soc_ok) or soc_num <= flor %}"
        "{% set band_uit = soc_ok and soc_num > flor + 2 %}"
        "{% set verkoop_blokkade = in_reserve or (prev != 'Ontladen' and not band_uit) %}"
        "{{ verkoop_blokkade }}"
    )
    def render(soc, prev=""):
        _S["sensor.accu_percentage"] = soc
        return tpl.render(prev=prev, states=lambda e: _S.get(e, "unknown"))
    # v1.8.5: band omgekeerd — instappen vereist soc > flor+2; eenmaal in
    # Ontladen blijft de verkoop open tot flor (tak-2-hysterese).
    assert render("12") == "True"       # diep onder reserve
    assert render("20") == "True"       # precies op flor: grens is '≤'
    assert render("21") == "True"       # fris besluit bij 21: nog geen instap (< flor+2)
    assert render("21", "Ontladen") == "False"   # al aan het verkopen: blijven tot flor
    assert render("23") == "False"      # boven flor+2: instap vrij
    assert render("23", "Ontladen") == "False"
    assert render("80", "Ontladen") == "False"
    assert render("unknown") == "True"  # fail-safe
    assert render("unavailable") == "True"
    assert render("-1") == "True"


async def test_shadow_huisreserve_is_apart_signaal_v190(hass):
    """v1.9.0: de huisreserve (flor) staat UIT de statuskeuze. De status is
    een zuivere prijs-/economiestatus; de reserve leeft apart in
    binary_sensor.shadow_accu_blokkade. Met flor 15: SOC 18 > flor → geen
    blokkade; SOC 12 < flor → blokkade on, en de latch houdt aan tot soc weer
    boven flor klimt (v1.9.0 fix #1: géén flor+2-uitstapband). Curtail blijft
    altijd door; Laden toont nooit een blokkade op de statussensor (het
    puur-SOC-signaal kan er wél on staan — de statussensor filtert)."""
    await _setup_shadow(hass)
    async def zet(daglijst):
        await _zet_daglijst(hass, daglijst)
    # flor 15 (async_set, geen write): SOC 21 moet buiten de reserve vallen
    # (signaal off), SOC ≤ 15 erbinnen (on). Met flor 20 zou de ladder
    # 18→21→23 precies op de rand vallen en de verwachtingen verwarren.
    hass.states.async_set("input_number.shadow_soc_min", "15")
    # v1.9.3: accu_reserve_pct is de PRIMARY reserve in shadow.yaml (flor);
    # shadow_soc_min alleen fallback. Deze test zet deliberately flor 15 —
    # dus beide, want async_set op shadow_soc_min zonder primary laat de
    # template op de gefaalde default 20 vallen en dan zit SOC 18 in_reserve
    # en kleurt de Spaar-tak de prijsstatus.
    hass.states.async_set("input_number.accu_reserve_pct", "15")
    hass.states.async_set("sensor.vandaag_verwachte_zonnestroom", "40.0")
    bs = lambda: hass.states.get("binary_sensor.shadow_accu_blokkade")
    # Prev leeg (initiele prev 'Spaar' van de setup zou anders meekleuren)
    await _zet_prev(hass, "")
    # 1) verkoop zou lonen (avondpiek boven eis), SOC 18 > flor 15:
    #    de status kiest puur op prijs (Neutraal of Ontladen); het puur-SOC-
    #    signaal staat OFF (18 zit ruim boven flor). Flor is hier expres 15
    #    gezet zodat de ladder 18→21→23 buiten de reserve valt en de latch
    #    niet per ongeluk meekleurt.
    await _trig(hass, 18)
    await zet(_daglijst_piek_met_pv(0.40, 0.30, 0.30, 0.05))
    await _trig(hass, 18)
    st = hass.states.get("sensor.shadow_status")
    assert st.state in ("Neutraal", "Ontladen"), f"prijsstatus bij hoge prijs, got {st.state}"
    assert bs().state == "off", f"SOC 18 > flor 15 → geen blokkade, got {bs().state}"
    # 2) SOC diep onder flor (12) → signaal on, en de latch houdt aan tot soc
    #    weer boven flor klimt (v1.9.0 fix #1: géén flor+2-uitstapband meer)
    await _trig(hass, 12)
    assert bs().state == "on", f"SOC 12 < flor → blokkade on, got {bs().state}"
    # 3) SOC 16 (net boven flor 15) → latch geeft vrij (boven flor)
    await _trig(hass, 16)
    assert bs().state == "off", f"SOC 16 boven flor → off, got {bs().state}"
    # 4) ruimtetak: R > 0 geeft Doorleveren, ONAFHANKELIJK van de prijskeuze.
    #    Bij SOC 12 en flor 20 klemt de doelformule (max(flor,...)) → doel 20,
    #    dus R negatief. Flor tijdelijk naar 5: doel = 100−40/92·100 ≈ 56,5?
    #    Nee — met S=40, C=92 is raw ≈ 56,5 > 5 → doel 56,5, nog steeds R<0.
    #    Eenvoudiger: hogere SOC dan doel. Zet flor 5 en SOC 60 → doel 56,5,
    #    R = +3,5 → ruimtetak vuurt terwijl de blokkade uit is (SOC ≥ flor+2).
    await hass.services.async_call(
        "input_number", "set_value",
        {"entity_id": "input_number.shadow_soc_min", "value": 5}, blocking=True)
    # v1.9.2: accu_reserve_pct is de primary-reserve van shadow.yaml en leeft in
    # MAIN — in deze geisoleerde fixture bestaat hij niet, dus set_value faalt
    # stil. async_set zet de state wél (de template leest alleen states()).
    hass.states.async_set("input_number.accu_reserve_pct", "5")
    await hass.async_block_till_done()
    await zet(_daglijst_attr(0.30, 0.40, 0.28, 0.30))
    await _trig(hass, 60)
    st = hass.states.get("sensor.shadow_status")
    assert st.state == "Doorleveren", f"R>0 → Doorleveren ook zonder verkoopmarge, got {st.state}"
    # terug naar flor 20 voor de volgende stappen
    await hass.services.async_call(
        "input_number", "set_value",
        {"entity_id": "input_number.shadow_soc_min", "value": 20}, blocking=True)
    hass.states.async_set("input_number.accu_reserve_pct", "20")
    await hass.async_block_till_done()
    # 5) negatieve prijs → curtail gaat ALTijd door (verplicht, geen keuze)
    await zet(_daglijst_attr(0.30, 0.40, 0.28, -0.02))
    await _trig(hass, 12)
    st = hass.states.get("sensor.shadow_status")
    assert st.state == "Ontladen (curtail)", f"curtail moet altijd door, got {st.state}"
    # 6) diepe dalprijs ONDER de reserve → status Laden én de blokkade MOET
    #    uit: goedkoop laden is juist hoe je boven de reserve komt.
    hass.states.async_set("input_number.shadow_w", "0")
    hass.states.async_set("input_number.shadow_m", "0")
    # v1.9.4: η_rt = shadow_eta-noodvallet 0,83 (gemeten rendements-helpers
    # bestaan niet in deze fixture). Twee valken blokkeerden hier 'Laden':
    # 1)
    #    curtail-uur (-0,02) uit stap 5 als diepste in-prijs in de top van de
    #    24u-venster-ladder → de herlaadkosten-sensor berekende h = 0,10 en
    #    overschreef daarmee elke handmatige h-doneer. Met eis = (h+w+m)/η ≈
    #    0,12 kon géén enkele prijsstructuur meer zuiver laden.
    # 2)
    #    De Spaar-tak steekt nu onder de reserve (SOC 12 ≤ flor 20) als
    #    in_reserve én n_top ≤ 0. Met een lege ladder na 'nu' is het
    #    ontlaadbudget nul → n_top 0 → Spaar wint vóór de Laad-tak.
    # Fix: schone ladder ZONDER negatief uur, met COMENDE dure toppen zodat
    # het ontlaadbudget (ontlaadbare_uren > 0) blijft — zonder budget valt de
    # Spaar-tak onmiddellijk binnen. De PV-dip van het vorige profiel viel
    # binnen het gezaaide zonvenster en werd als goedkoopste herlaad meegenomen
    # (h=0,10 → verkoop-eis ~0,12 → geen enkele prijsstructuur kon zuiver
    # laden). Nu: dal 0,30 rond 'nu', avondpiek 0,80 BINNEN de resterende
    # uren van vandaag. De herlaadkosten-formule is min(in) over 24u (PV-tak
    # is leeg bij verwachte PV 0), dus h = 0,30 vanzelf — geen doneer nodig.
    # Eis = (0,30+0,025+0,015)/0,83 ≈ 0,409 → uit 0,30 verkoopt niet;
    # V = 0,83 × gemiddelde(top) ≈ 0,656 → Laden-eis in+w+m = 0,34 < V−H =
    # 0,651 én de dure toppen geven ontlaadbudget > 0. Signaal (puur SOC) en
    # status (prijs) blijven zo apart verifieerbaar.
    hass.states.async_set("input_number.shadow_w", "0.025")
    hass.states.async_set("input_number.shadow_m", "0.015")
    from datetime import datetime, timedelta, timezone as tz
    now_dt = datetime.now(tz.utc)
    base = int(now_dt.timestamp())
    # v1.9.3: h is niet los te forceren (de template herberekent h na elke
    # daglijst-write), dus de ladder zélf bepaalt h: dal met in=0,30 net na
    # now (PV-tak min(uit)=0,80) → h = min(in) = 0,30. Verkoop-eis
    # (h+w+m)/η = 0,34/0,83 ≈ 0,41 → uit 0,30 verkoopt niet. V = η × gemid-
    # delde hoogste 12 in-prijzen = 0,83×0,80 = 0,664 → Laden-eis in+w+m =
    # 0,34 < g_laden = V−H = 0,659 → laden vrij, ook onder de huisreserve
    # (die is het aparte binaire blokkade-signaal, geen statusdrempel).
    _toppen = [{"t": (now_dt + timedelta(hours=6, minutes=15 * i)).isoformat(),
                "e": base + 21600 + 900 * i, "p": 0.2, "in": 0.80, "uit": 0.80}
               for i in range(12)]
    await zet([
        {"t": (now_dt - timedelta(seconds=7.5)).isoformat(), "e": base - 7,
         "p": 0.2, "in": 0.30, "uit": 0.80},
        {"t": (now_dt + timedelta(minutes=15)).isoformat(), "e": base + 900,
         "p": 0.2, "in": 0.30, "uit": 0.80},
    ] + _toppen)
    await hass.async_block_till_done()
    assert float(hass.states.get("sensor.shadow_herlaadkosten").state) == 0.30, \
        "h moet 0,30 zijn uit de ladder zelf; anders ziet de template het dal niet"
    await _trig(hass, 12)
    # v1.9.x: het SOC-verbruik van de huisreserve zit in de DYNAMISCH
    # genormaliseerde verbruiksband (shadow_m), niet in een aparte sensor.
    # Bij PV-dekking (w=0) is er geen reserveverbruik → laden blijft vrij;
    # de reserve is nog steeds zichtbaar via shadow_soc_min (20%).
    st = hass.states.get("sensor.shadow_status")
    assert st.state == "Laden", (
        f"goedkoop laden moet vrij zijn, got {st.state} attrs={dict(st.attributes)}")
    # Het SIGNAAL is puur-SOC: bij SOC 12 < flor staat het on, en de
    # 'blokkade'-spiegel op de statussensor is dezelfde puur-SOC-waarde.
    # Statusafhankelijk filteren kan hier niet: attributes worden vóór de
    # state gezet (this.state is dan stale) en update_on_state forceert bij
    # een statuswissel juist één render met die oude basis.
    assert bs().state == "on", f"puur-SOC-signaal bij SOC 12, got {bs().state}"
    a = dict(hass.states.get("sensor.shadow_status").attributes)
    assert a["blokkade"] == "on", f"puur-SOC-spigel ook op statussensor, got {a}"
    # 7) SOC precies gelijk aan flor (20) → grens is '≤', dus blokkade on
    await zet(_daglijst_piek_met_pv(0.40, 0.30, 0.30, 0.05))
    await _trig(hass, 20)
    assert bs().state == "on", f"soc==flor → on, got {bs().state}"
    # 8) v1.9.0 fix #1: net boven flor (21) geeft de latch VRIJ (geen
    #    flor+2-band meer). De STATUS doet mee op prijs (hoge avondpiek boven
    #    de eis ⇒ Ontladen).
    await _trig(hass, 21)
    assert bs().state == "off", f"21 boven flor → latch vrij, got {bs().state}"
    st = hass.states.get("sensor.shadow_status")
    assert st.state == "Ontladen", f"prijsstatus bij hoge piek ≥ Ontladen, got {st.state}"
    # 9) SOC unavailable → fail-safe: blokkade on, status blijft prijs-gebaseerd
    hass.states.async_set("sensor.accu_percentage", "unavailable")
    await hass.async_block_till_done()
    await _trig(hass, None)
    assert bs().state == "on", f"unknown/unavailable SOC → fail-safe on, got {bs().state}"
    st = hass.states.get("sensor.shadow_status")
    assert st.state in ("Neutraal", "Ontladen"), f"status blijft prijs-gebaseerd, got {st.state}"
async def test_shadow_hysterese_en_kwartierindex(hass):
    """v1.5.2 — de twee anti-knipperingsfixes:
    1. Hysterese: vlakke prijsspel rond de V-grens (in+w+m ≈ V) mag NIET elk
       kwartier Laden↔Neutraal tikken. Zolang de prijs binnen ±H van de grens
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
    # v1.7.7: de beslis-template deelt de Laden-grens níét meer op η_laad
    # (V bevat al η_rt = η_laad × η_ontlaad; dubbel telden we het laadverlies).
    # Beslisregel: in_nu + w + m < V − H. De V-sensor filtert op e >= nu_epoch,
    # dus verstreken entries tellen NIET mee — top-12 = alleen de 2 dure
    # toekomstprijzen (0,40). V = 0,83 × 0,40 = 0,332; Laden-grens V − H = 0,327.
    # Hysterese-band in_nu + w + m ∈ (0,327 ; 0,337) → in_nu ∈ (0,287 ; 0,297).
    # P1: in_nu = 0,295 → 0,295+0,040 = 0,335 > V = 0,332 → Neutraal
    # P2: in_nu = 0,285 → 0,285+0,040 = 0,325 < V−H = 0,327 → Laden
    # P3: in_nu = 0,292 → 0,292+0,040 = 0,332 → binnen band → Laden
    # P4: in_nu = 0,30  → 0,30+0,040 = 0,340 > V+H = 0,337 → uit Laden
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

    # v1.7.7: η-laad schrapt — V bevat al η_rt (laad × ontlaad); de oude
    # in_nu/η_laad + w + m < V − H telt het laadverlies dubbel. Nieuwe
    # beslisregel: in_nu + w + m < V − H.
    # V = 0,83 × 0,40 = 0,332; Laden-grens V − H = 0,327; w+m = 0,040.
    # Hysterese-band: in_nu + w + m ∈ (0,327 ; 0,337) → in_nu ∈ (0,287 ; 0,297)
    # P1: in_nu = 0,295 → 0,295+0,040 = 0,335 > V = 0,332 → Neutraal
    # P2: in_nu = 0,285 → 0,285+0,040 = 0,325 < V−H = 0,327 → Laden
    # P3: in_nu = 0,292 → 0,292+0,040 = 0,332 → binnen band → Laden
    # P4: in_nu = 0,30  → 0,30+0,040 = 0,340 > V+H = 0,337 → uit Laden
    # P1: in_nu = 0,295 → 0,335 < V+H → Spaar (v1.9.0: de oude else-Spaar is
    #     weg; Neutraal ís de verbruiksband in ≥ V+H en uit ≤ eis+H)
    await _zet_laden(0.295)
    await _trig(hass, 50)
    st = hass.states.get("sensor.shadow_status")
    assert st.state == "Spaar", f"P1: verwacht Spaar, got {st.state}"

    # P2: in_nu = 0,285 → Laden
    await _zet_laden(0.285)
    await _trig(hass, 50)
    st = hass.states.get("sensor.shadow_status")
    if st.state != "Laden":
        import time as _t
        dag = hass.states.get("sensor.stroomprijs_daglijst")
        vandaag = dag.attributes.get("vandaag", []) if dag else []
        nu2 = [e for e in vandaag if e.get("e", 0) <= _t.time()]
        in_nu = nu2[-1]["in"] if nu2 else None
        V = float(hass.states.get("sensor.shadow_v_waarde_opgeslagen_kwh").state)
        H = float(hass.states.get("input_number.shadow_hysteresis").state)
        w = float(hass.states.get("input_number.shadow_w").state)
        m = float(hass.states.get("input_number.shadow_m").state)
        prev = hass.states.get("input_text.shadow_status_vorige")
        prev = prev.state if prev else None
        raise AssertionError(
            f"P2: verwacht Laden, got {st.state}; "
            f"in_nu={in_nu} V={V} H={H} w={w} m={m} "
            f"prev={prev} | in+w+m={in_nu+w+m if in_nu else '?'} "
            f"g_laden={V-H} g_laden_uit={V+H}")
    assert st.state == "Laden", f"P2: verwacht Laden, got {st.state}"
    # P3: in_nu = 0,292 → 0,292+0,04 = 0,332 → = V → binnen band → Laden
    await hass.services.async_call(
        "input_text", "set_value",
        {"entity_id": "input_text.shadow_status_vorige", "value": "Laden"},
        blocking=True)
    await hass.async_block_till_done()
    await _zet_laden(0.292)
    await _trig(hass, 50)
    st = hass.states.get("sensor.shadow_status")
    if st.state != "Laden":
        import time as _t
        dag = hass.states.get("sensor.stroomprijs_daglijst")
        vandaag = dag.attributes.get("vandaag", []) if dag else []
        nu2 = [e for e in vandaag if e.get("e", 0) <= _t.time()]
        in_nu = nu2[-1]["in"] if nu2 else None
        V = float(hass.states.get("sensor.shadow_v_waarde_opgeslagen_kwh").state)
        H = float(hass.states.get("input_number.shadow_hysteresis").state)
        prev = hass.states.get("input_text.shadow_status_vorige")
        prev = prev.state if prev else None
        val = in_nu + 0.025 + 0.015 if in_nu else '?'
        raise AssertionError(
            f"P3: verwacht Laden, got {st.state}; "
            f"in_nu={in_nu} V={V} H={H} prev={prev} "
            f"| in+w+m={val} g_laden_uit={V+H}")
    assert st.state == "Laden", (
        f"hysterese faalt, got {st.state}")

    # P4: in_nu = 0,30 → 0,30+0,04=0,340 > V+H=0,337 → buiten band → uit Laden
    await _zet_laden(0.30)
    await _trig(hass, 50)
    st = hass.states.get("sensor.shadow_status")
    assert st.state != "Laden", (
        f"0,30+0,04=0,340 > V+H=0,337 moet uit Laden, got {st.state}")

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


def _zes(in_nu, in_top, uit_nu, uit_top):
    """v1.9.3: 6-kwartieren ladder — posities 0-1 dragen de 'nu'-waarden,
    posities 2-5 de dure top. Eerste twee kwartieren binnen het meetvenster."""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    out = []
    pairs = ([(in_nu, uit_nu)] * 2 + [(in_top, uit_top)] * 4
             + [(0.30, 0.30)] * 8)
    for i, (p_in, p_uit) in enumerate(pairs):
        t = (now - timedelta(seconds=7.5) + timedelta(minutes=15 * i)).isoformat()
        out.append({"t": t, "e": int(now.timestamp()) + (-7.5 + 900 * i),
                    "p": 0.2, "in": p_in, "uit": p_uit})
    return out


async def test_shadow_neutraal_als_verbruiksband(hass):
    """v1.8.4 — Jans definitie van Neutraal: te duur om te laden (in + w + m ≥
    V + H) én te goedkoop om te verkopen (uit ≤ verkoop-eis + H), mét η al in V
    (top-n × roundtrip) en in de eis ((herlaad + slijtage)/η). Dan geeft de accu het
    huis stroom: dure nettarieven ontlopen. Daartoe was deze band bedoeld;
    voorheen viel zo'n kwartier stil op Spaar (huis op net)."""
    await _setup_shadow(hass)
    hass.states.async_set("sensor.vandaag_verwachte_zonnestroom", "0.0")
    hass.states.async_set("sensor.verwachte_opbrengst_morgen", "0.0")
    await hass.async_block_till_done()
    #    soc_min laag: flor mag hier niet storen (reserveregelement heeft eigen test).
    #    v1.9.2: de primary-reserve is accu_reserve_pct — die moet dus óf laag,
    #    óf het vermogen omhoog; hier beide helpers op de oude voet gezet.
    await hass.services.async_call(
        "input_number", "set_value",
        {"entity_id": "input_number.shadow_soc_min", "value": 5}, blocking=True)
    # v1.9.2: accu_reserve_pct is de primary-reserve van shadow.yaml en leeft in
    # MAIN — in deze geisoleerde fixture bestaat hij niet, dus set_value faalt
    # stil. async_set zet de state wél (de template leest alleen states()).
    hass.states.async_set("input_number.accu_reserve_pct", "5")
    # v1.9.3: η_rt = 1 (suite-referentie). Ladder: twee 'nu'-kwartieren
    # in=0,62/uit=0,30 + vier dure topkwartieren in=0,60.
    #   V = η_rt · gemiddelde van de top-n in-prijzen = 1 · 0,60 = 0,60
    #   h = min(in) over komende 24 u = 0,60 (de ladder zélf, geen doneer)
    #   → eis = (h+w+m)/η_rt = (0,60+0,025+0,015)/1 = 0,64
    # nu-kwartier in = 0,62 / uit = 0,30:
    #   Laden? laadtak eist in+w+m < V−H = 0,58 → 0,66 ≥ 0,58 → NEE (te duur)
    #   Verkopen? eis + H = 0,66 → uit 0,30 ≤ 0,66 → NEE (te goedkoop)
    #   → verbruiksband → Neutraal.
    await _zet_daglijst(hass, _zes(0.62, 0.60, 0.30, 0.30))
    await _trig(hass, 50)
    st = hass.states.get("sensor.shadow_status")
    assert st.state == "Neutraal", (
        f"te duur te laden + te goedkoop te verkopen → Neutraal, got {st.state} "
        f"attrs={dict(st.attributes)}")
    # 2) tegenpool: uit boven de verkoop-eis is het géén neutrale zone meer.
    #    Doneer h = 0,30 (goedkope herkansing) → eis = 0,34;
    #    uit 0,62 > eis + H = 0,36 → de verkooptak neemt over.
    #    Let op hysterese: vanuit prev=Neutraal houdt de neutraaltak zolang
    #    in ≥ V−H (anti-fladder, v1.9.0) — dus eerst via een goedkoop laad-
    #    kwartier van prev af, dan pas de verkoopladder. SOC is prijszuiver,
    #    geen poort.
    #   Tussenstand: prev rechtstreeks naar Laden via de log-route (prev-arg).
    await _zet_daglijst(hass, _zes(0.62, 0.60, 0.62, 0.62))
    await _trig(hass, 50, herlaad=0.30, prev="Laden")
    st = hass.states.get("sensor.shadow_status")
    assert st.state == "Ontladen", (
        f"uit boven verkoop-eis → verkooptak, niet de verbruiksband, got {st.state}")
    # 3) v1.9.0: óók onder de huisreserve beslist de status puur op prijs —
    #    de blokkade leeft in binary_sensor.shadow_accu_blokkade (eigen test).
    #    Zelfde band als stap 1: h = min(in) = 0,60 → eis 0,64; in 0,62 te duur
    #    om te laden, uit 0,30 te goedkoop om te verkopen → Neutraal, ook bij
    #    SOC 4 (verkoop-/laadtak kijken niet naar SOC). Prev terug naar
    #    Neutraal via dezelfde log-route als in productie.
    # v1.9.3: reserve tijdelijk naar 0 — de status beslist puur op prijs, dus
    # voor dit deel van de test moet de ruimte-/reserve-tak uitgeschakeld zijn
    # (accu_reserve_pct is primary-reserve; flof 20 maakt SOC 4 in_reserve en
    # de Spaar-tak gooit dan roet in het eten zolang η_rt > 1 de ladder-V boven
    # in duwt). De binaire blokkade-Sensor kijgt hierdoor géén SOC ≤ flor meer,
    # dus diens assertie verhuist naar een eigen scenario (test_shadow_helpers
    # / accu-blokkade-suite).
    hass.states.async_set("input_number.accu_reserve_pct", "0")
    await _zet_daglijst(hass, _zes(0.62, 0.60, 0.30, 0.30))
    await _trig(hass, 4, prev="Neutraal")
    st = hass.states.get("sensor.shadow_status")
    assert st.state == "Neutraal", (
        f"prijsstatus is SOC-onafhankelijk, got {st.state}")
    bs = hass.states.get("binary_sensor.shadow_accu_blokkade")
    assert bs is not None and bs.state == "on", (
        f"SOC 4 ≤ flor → apart signaal aan, got {bs.state if bs else None}")


async def _hysterese_fixture(hass):
    """Gemeenschappelijke setup voor de v1.8.5-hysterese-tests: soc_min laag
    zodat de reserve-band niet meespeelt, daglijst met dure nu-in (laden loont
    niet) en een uit-prijs in de band rond de verkoop-eis. Retourneert de
    V-waarde zodat de test de g_eis-grenzen kan afleiden."""
    await _setup_shadow(hass)
    hass.states.async_set("sensor.vandaag_verwachte_zonnestroom", "0.0")
    hass.states.async_set("sensor.verwachte_opbrengst_morgen", "0.0")
    await hass.async_block_till_done()
    # v1.9.3: flor naar 5. De Spaar-/reserve-takken van de status lezen flor
    # PRIMARY uit input_number.accu_reserve_pct (v1.9.2); binary_sensor.shadow_accu_blokkade
    # en het blokkade-attribuut lezen input_number.shadow_soc_min. Beide zetten:
    # accu_reserve_pct als state (main-helper, niet in dit package), soc_min via
    # de service-call zoals hieronder altijd al gebeurde. Zonder deze zet blijft
    # flor 20 en kleurt de reserve-band de prijs-/hysterasetests.
    hass.states.async_set("input_number.accu_reserve_pct", "5")
    await hass.services.async_call(
        "input_number", "set_value",
        {"entity_id": "input_number.shadow_soc_min", "value": 5}, blocking=True)
    # v1.9.3: η_rt = 1 voor deze hysterese-tests. In deze geïsoleerde fixture
    # bestaan de gemeten rendements-helpers niet, dus η_rt valt terug op de
    # noodvallet shadow_eta — die zetten we expliciet op 1. Daarmee wordt de
    # eis exact h+w+m (de EIS-deeltal η mag de bandcijfers 0,435/0,445 níét
    # verschuiven: met η=0,83 werd de eis 0,53 en verloor de test zijn
    # instap-/uitstapdrempel). V = topgemiddelde zonder rendementsruis.
    hass.states.async_set("input_number.shadow_eta", "1")
    await hass.async_block_till_done()


def _lees_eis(hass):
    """Verkoop-eis ná de daglijst (de sensor is unavailable zolang die leeg is)."""
    st = hass.states.get("sensor.shadow_verkoop_eis")
    assert st.state not in ("unavailable", "unknown"), f"eis niet berekend: {st.state}"
    return float(st.state)


async def _zet_prev(hass, value):
    """Prev-status rechtstreeks schrijven via async_set — BEWUST géén
    set_value-service-call. HA triggert de status-sensor op writes van
    input_text.shadow_status_vorige; zo'n herberekening leest de net gezette
    prev gecombineerd met de OUDE daglijst/SOC en de log-automation overschrijft
    de prev dan meteen met die oude kant. async_set verandert alleen de state
    zonder de sensor te triggeren; de volgende _trig zet daglijst/SOC en rendert
    ééns met de nieuwe prev."""
    hass.states.async_set("input_text.shadow_status_vorige", value)
    await hass.async_block_till_done()





async def test_shadow_ontladen_hysterese_v185(hass):
    """v1.8.5 — de uit-tak ving vóór deze fix met g_eis_uit (= eis − H) alles op
    tot onder de instapdrempel eis + H: instappen gebeurde al op eis−H en de
    instaptak was dode code. Nu: instappen vereist uit > eis + H; blijven
    vereist prev == 'Ontladen' en uit > eis − H. Uit de band (tussen eis−H en
    eis+H) hangt de status aan de prev-kant.

    Cijfers: η_rt=1, min-in = 0,40 → eis = 0,44 (herlaad + w + m); H = 0,005 →
    instapdrempel 0,445, uitstapdrempel 0,435; uit = 0,44 zit precies ertussen.
    V = topgemiddelde ≈ 0,4267 → g_laden_uit = 0,4317 < in+w+m 0,44 → laden
    loont niet. v1.9.2 reserve-aware: flor = accu_reserve_pct = 20, SOC 51 →
    kwh_nog = 31% × 92 kWh × η_uit 0,9 ≈ 25,6 → n_top = floor(25,6/4,5) = 5;
    de twee dure slots (incl. het lopende kwartier) passen in het budget en
    vormen de hele top → ontladen toegestaan zolang de band dat wil."""
    await _hysterese_fixture(hass)
    # v1.9.2 reserve-aware: flor = accu_reserve_pct = 20 en SOC 50 →
    # kwh_nog = 30% × 92 kWh × η_ontlaad 0,9 ≈ 24,8 kWh. Bij de default P=5 kW
    # zijn er dan maar ~4 dure slots budget; deze tests draaien de PRIJSHYSTERESE
    # met hogere prijzen in meer slots, dus P naar minimum 0,1 kW → budget
    # ruimschoots groter dan het aantal dure slots (de band zelf wordt getest,
    # niet de kap). Echte vermogens staan in de product-helper; hier minimaal.
    # v1.9.2: accu_vermogen_uit_kw is een MAIN-helper en bestaat niet in de
    # geisoleerde shadow-fixture; de service-call hierboven faalde dus stil en
    # de template viel terug op z'n eigen fallback (5 kW): budget ~4 u = 4
    # slots < de dure slots van deze daglijst → de top-verkiezing verstikte de
    # verkooptak. async_set zet de state wél → P 0,1 kW, géén kap.
    hass.states.async_set("input_number.accu_vermogen_uit_kw", "0.1")
    await hass.async_block_till_done()
    await _zet_daglijst(hass, _daglijst_voortgang(0.40, 0.44, 0.44, 0.44))
    eis = _lees_eis(hass)
    assert abs(eis - 0.44) < 1e-9, f"fixture-eis verrast: {eis}"
    # 1) prev 'Laden' + uit = v_eis → de uit-band is te laag voor instappen.
    #    η_rt=1 → V = topgemiddelde ≈ 0,4267, eis = h+w+m = 0,44. De
    #    Ontladentak vraagt uit > eis+H (0,445); uit 0,44 zit eronder, dus er
    #    wordt zónder prev-ontlading NOOIT ingestapt. De Laad-prev-route wint
    #    wel: in+w+m 0,44 … nee — die route houdt Laden alleen vast binnen
    #    V+H (g_laden_uit 0,4317)? 0,44 valt erbuiten, dus prev Laden kan hier
    #    níét blijven hangen; de keten valt door tot de Spaar-tak (kale in_nu
    #    0,40 < V+H). Neutraal is pas de rest bij in ≥ V+H. Deze stap toetst
    #    dat de band zélf niet op Ontladen instapt, ongeacht de prev-kant.
    await _trig(hass, 51)
    st = hass.states.get("sensor.shadow_status")
    assert st.state == "Spaar", (
        "band zonder ontlaad-prev → géén Ontladen-instap (keten valt door tot "
        f"Spaar: kale in_nu < V+H), got {st.state} attrs={dict(st.attributes)}")
    # 2a) instaproute: verhoog de uit-prijs BOVEN de instapdrempel (eis+H) →
    #     de keten stapt zelf op Ontladen in en de prev-route (log-automation)
    #     heeft dan in productie 'Ontladen' als geheugen. In deze fixture leeft
    #     die automation niet; dus zetten we de prev via productieve schrijfwijze
    #     nadat dézelfde daglijst-render op Ontladen uitkwam — geen kunstmatige
    #     prev uit het niets (stap 1 gaf Spaar, dus prev='Ontladen' had hier nog
    #     nooit bestaan).
    await _zet_daglijst(hass, _daglijst_voortgang(0.40, 0.46, 0.46, 0.46))
    await _trig(hass, 51)
    st = hass.states.get("sensor.shadow_status")
    assert st.state == "Ontladen", (
        f"uit boven eis+H → instap in de verkooptak, got {st.state} "
        f"attrs={dict(st.attributes)}")
    # 2b) prev='Ontladen' + terug de band in (uit = v_eis, tussen eis−H en
    #     eis+H) → binnen de band blijft men aan het verkopen: uit > eis − H
    #     volstaat zolang de prev Ontladen is. async_set i.p.v. set_value: een
    #     service-call is een write en de status-sensor triggert op writes van
    #     input_text.shadow_status_vorige — die herberekening zou de net gezette
    #     prev meteen overlopen met de oude kant.
    #     v1.9.3: volgorde is alles. Zet de prev via async_set, dán pas de
    #     band-daglijst: de daglijst-write triggert de sensor-render die de
    #     nieuwe prev wél ziet (een set_value-call zonder de log-automation
    #     faalde hier stil op de trigger).
    #     v1.9.3: volgorde is alles. Zet de prev via async_set, dán pas de
    #     band-daglijst; de daglijst-write triggert de sensor-render die de
    #     nieuwe prev wél ziet. De uit-Ladder blijft 0,46: het lopende uur
    #    (0,44) valt in de hysterese-band, maar de komende uren blijven boven
    #     de instapdrempel zodat de top-verkiezing dit kwartier niet uit het
    #     budget knippert (bij een vlakke 0,44-ladder staat er niets meer boven
    #     de eis → in_top onbereikbaar → val door naar Spaar).
    await _zet_prev(hass, "Ontladen")
    await _zet_daglijst(hass, _daglijst_voortgang(0.40, 0.44, 0.46, 0.46))
    await _trig(hass, 51)
    st = hass.states.get("sensor.shadow_status")
    assert st.state == "Ontladen", (
        f"uit tussen eis−H en eis+H met prev Ontladen → Ontladen, got {st.state} "
        f"attrs={dict(st.attributes)}")


async def test_shadow_reserve_band_flappert_niet_v185(hass):
    """v1.8.5 — de oude band (instap ≤ flor, uitstap > flor+2) flopte elke
    tick. v1.9.0 fix #1 maakt de band STRICTER: instappen zodra soc ≤ flor,
    latch houdt aan tot soc weer boven flor klimt (géén flor+2-uitstapband).
    Daarmee is er geen grijs gebied tussen flor en flor+2 waarin het signaal
    per tick kon kantelen.

    Verkoopsituatie: η_rt=1 → eis = 0,44; uit = 0,45 > eis + H.
    De STATUS kiest puur op prijs — bij elke SOC Ontladen. De anti-fladder-
    eigenschap zit in binary_sensor.shadow_accu_blokkade: vier identieke
    ticks bij dezelfde SOC mogen het signaal niet doen wisselen. Bij SOC 21
    (boven flor 20) is het signaal off en blijft off; bij SOC 18 (onder flor)
    on; bij terugkeer naar 21 geeft de latch direct vrij (soc > flor).
    """
    await _hysterese_fixture(hass)
    # v1.9.2: accu_vermogen_uit_kw + accu_reserve_pct zijn MAIN-helpers en
    # bestaan niet in deze geisoleerde fixture; eerdere set_value-calls faalden
    # dus STIL. De template-valt terug op P=5 kW → budget ~4 u = 4 slots, en
    # deze daglijst heeft méér dure slots dan het verleden → de top-verkiezing
    # verstikte de verkooptak (got 'Neutraal'). async_set zet de states wél:
    # P 0,1 kW (géén kap) en reserve 0 voor de STATUS-takken (geen
    # Spaar-overstemming). De binaire signaaltesten hieronder toetsen de band
    # bij flor 20 — de productie-value van accu_reserve_pct én de soc_min-
    # default — en binary_sensor.shadow_accu_blokkade leest UITSLOITEND
    # shadow_soc_min (de hysterese-fixture zette die op 5). Dus soc_min terug
    # naar 20; de status-Spaar-tak blijft buiten spel via accu_reserve_pct=0.
    hass.states.async_set("input_number.accu_vermogen_uit_kw", "0.1")
    hass.states.async_set("input_number.accu_reserve_pct", "0")
    await hass.services.async_call(
        "input_number", "set_value",
        {"entity_id": "input_number.shadow_soc_min", "value": 20}, blocking=True)
    await _zet_daglijst(hass, _daglijst_voortgang(0.40, 0.44, 0.45, 0.45))
    # 1) status is prijszuiver: ook bij SOC 21 gewoon Ontladen. Prev leeg
    #    zetten: de log-automation heeft 'Spaar' achtergelaten en in deze
    #    fixture is Spaar een vers besluit (geen writes).
    await _zet_prev(hass, "")
    await _trig(hass, 21)
    st = hass.states.get("sensor.shadow_status")
    assert st.state == "Ontladen", (
        f"prijsstatus kent geen SOC-poort, got {st.state}")
    # 2) het SIGNAAL flopt niet: vier identieke ticks bij SOC 21 (net boven
    #    flor 20) — puur-SOC → off, en blijft off zolang de inputs gelijk zijn.
    for i in range(4):
        await _trig(hass, 21)
        bs = hass.states.get("binary_sensor.shadow_accu_blokkade")
        assert bs.state == "off", (
            f"tick {i + 1}/4 bij SOC 21: signaal mag niet aan/uit fladderen, got {bs.state}")
    # 3) onder flor → signaal on.
    await _trig(hass, 18)
    bs = hass.states.get("binary_sensor.shadow_accu_blokkade")
    assert bs.state == "on", f"SOC 18 < flor 20: blokkade on, got {bs.state}"
    # 4) v1.9.0 fix #1: terug boven flor (21) → latch geeft DIRECT vrij (geen
    #    flor+2-band meer die nog vasthoudt).
    await _trig(hass, 21)
    bs = hass.states.get("binary_sensor.shadow_accu_blokkade")
    assert bs.state == "off", (
        f"SOC 21 > flor: strikte latch geeft vrij, got {bs.state}")
    # 5) nog hoger (23) → blijft off
    await _trig(hass, 23)
    bs = hass.states.get("binary_sensor.shadow_accu_blokkade")
    assert bs.state == "off", (f"SOC 23 boven flor: blokkade vrij, got {bs.state}")


async def test_shadow_neutraal_bandbreedte_v185(hass):
    """v1.9.0: de SOC-band is uit de statuskeuze — de reserve leeft in
    binary_sensor.shadow_accu_blokkade. Wat blijft is de PRIJSHYSTERESE rond
    V ± H (stap 4): een vers besluit spaart bij in < V + H; vanuit Neutraal
    houdt de neutraaltak aan zolang in ≥ V − H, en pas daaronder kapt de
    Spaar-tak om. Zelfde scenario, nu zonder SOC-verwachtingen: overal SOC
    21, flor 20 — de status doet daar niets mee."""
    await _hysterese_fixture(hass)
    # v1.9.2: accu_vermogen_uit_kw + accu_reserve_pct zijn MAIN-helpers en
    # bestaan niet in deze geisoleerde fixture; eerdere set_value-calls faalden
    # dus STIL. De template-valt terug op P=5 kW → budget ~4 u = 4 slots, en
    # deze daglijst heeft méér dure slots dan het verleden → de top-verkiezing
    # verstikte de verkooptak (got 'Neutraal'). async_set zet de states wél:
    # P 0,1 kW (géén kap) en reserve 0 (geen Spaar-overstemming).
    hass.states.async_set("input_number.accu_vermogen_uit_kw", "0.1")
    hass.states.async_set("input_number.accu_reserve_pct", "0")
    await hass.async_block_till_done()
    # Verbruiksgeval met η_rt = 1 (shadow_eta=1 in de fixture). De eerste twee
    # kwartieren van _daglijst_voortgang bepalen in_nu (eerste verstreken
    # kwartier); de dure prijzen bepalen V via het top-12-gemiddelde. Met
    # dure=in 0,39 is élke toekomstprijs 0,39 → V = 0,39 exact. Dus
    # g_laden_uit = V + H = 0,395 en g_laden = V − H = 0,385; in_nu = 0,39
    # zit midden in de band V±H.
    await _zet_daglijst(hass, _daglijst_voortgang(0.39, 0.39, 0.30, 0.30))
    # 1) prev leeg (vers besluit): in 0,39 < V+H = 0,395 → Spaar-tak wint.
    await _zet_prev(hass, "")
    await _trig(hass, 21)
    st = hass.states.get("sensor.shadow_status")
    assert st.state == "Spaar", (
        f"vers besluit + in < V+H → Spaar, got {st.state} attrs={dict(st.attributes)}")
    # 2) prev Neutraal (dezelfde daglijst): in 0,39 ≥ V−H = 0,385 → de
    #    neutraaltak (vóór de Spaar-tak) houdt aan → géén fladder rond V.
    await _zet_prev(hass, "Neutraal")
    await _trig(hass, 21)
    st = hass.states.get("sensor.shadow_status")
    assert st.state == "Neutraal", (
        f"prev Neutraal + in ≥ V−H → Neutraal blijft (geen fladder), got {st.state}")
    # 3) in_nu zakt naar 0,38 (< V−H = 0,385): de neutraaltak valt af en de
    #    Spaar-tak pakt — vanuit Neutraal is er dus wél een route naar beneden.
    await _zet_daglijst(hass, _daglijst_voortgang(0.38, 0.39, 0.30, 0.30))
    await _trig(hass, 21)
    st = hass.states.get("sensor.shadow_status")
    assert st.state == "Spaar", (
        f"in < V−H → overschakel naar Spaar, got {st.state}")

async def test_bevroren_daglijst_geen_besluit(hass):
    """v1.7.8: is het laatste verstreken kwartier ouder dan 45 min (bevroren
    daglijst — bijv. na middernacht als 'vandaag' nog de prijzen van gisteren
    bevat), dan beslist de shadow niet: status blijft 'unavailable'."""
    import time
    await _setup_shadow(hass)
    now = time.time()
    dag = [
        {"t": now - 3600, "e": now - 3500, "p": 0.2, "in": 0.05, "uit": 0.05},
        {"t": now + 900, "e": now + 1800, "p": 0.2, "in": 0.40, "uit": 0.30},
    ]
    await _zet_daglijst(hass, dag)
    await _trig(hass, 50)
    st = hass.states.get("sensor.shadow_status")
    assert st.state == "unavailable", (
        f"bevroren lijst (60 min oud) mag geen besluit leveren, got {st.state}")


async def test_shadow_curtail_geen_verkoop_hysterese_v186(hass):
    """v1.8.6 (stap 5, keuze vastgelegd): 'Ontladen (curtail)' telt NIET mee in de
    verkoop-hysterese — bewuste keus, deels door de vorige review gedragen.

    Curtail is géén verkoop maar een verplichte export-limiet (grid-operator):
    zodra 'uit' weer boven 0 komt, geldt de instapregel van een VERS besluit —
    uit > verkoop-eis + H EN soc > flor (v1.9.0: de SOC-poort zit niet meer in
    de beslisketen; binary_sensor.shadow_accu_blokkade is het apart te raadplegen
    signaal — de test checkt hier expliciet dat signaal mee). Pas daarna mag de
    gewone Ontladen-band beginnen. Als curtail wél zou meetellen, zou de instap
    direct na een curtail doorgaan binnen de reserveband — de flapper-test
    bestaat precies om dat te voorkomen.
    """
    await _setup_shadow(hass)
    # η_rt=1 via shadow_eta (gemeten rendements-helpers bestaan hier niet),
    # zodat de verkoop-eis exact te berekenen is: min-in + w + m.
    await hass.services.async_call(
        "input_number", "set_value",
        {"entity_id": "input_number.shadow_eta", "value": 1}, blocking=True)
    # v1.9.2: bij flor 20 / SOC 21 is het onlaadbudget ~1 kWh → n_top zou 0 of 1
    # zijn en de verkooptak stikken. P op minimum → budget ruimschoots.
    # v1.9.2: accu_vermogen_uit_kw is een MAIN-helper en bestaat niet in de
    # geisoleerde shadow-fixture; de service-call hierboven faalde dus stil en
    # de template viel terug op z'n eigen fallback (5 kW): budget ~4 u < de
    # dure slots van deze daglijst → de top-verkiezing verstikte de verkooptak.
    # async_set zet de state wél → P 0,1 kW, géén kap.
    hass.states.async_set("input_number.accu_vermogen_uit_kw", "0.1")
    await hass.async_block_till_done()
    await hass.async_block_till_done()
    # SOC 21: in de reserveband (flor 20..22) → verkoop is hier geblokkeerd.
    # Daglijst: nu-kwartier duurt (in 0.50 → laden loont níét; uit 0.30),
    # straks goedkooper (in 0.30 → V wordt laag, verkoop-eis laag).
    await _zet_daglijst(hass, _daglijst_voortgang(0.30, 0.50, 0.30, 0.10))
    await _trig(hass, 21)
    # 1) negatieve uit → curtail is verplicht en gaat door, óók onder de band
    await _zet_daglijst(hass, _daglijst_voortgang(0.30, 0.50, -0.02, 0.10))
    await _trig(hass, 21)
    st = hass.states.get("sensor.shadow_status")
    assert st.state == "Ontladen (curtail)", f"curtail gaat door, got {st.state}"
    # 2) uit springt terug boven de verkoop-eis, SOC 21 (flor 20 → signaal off):
    #    curtail telt níét als 'Ontladen' voor de hysterese → vers besluit.
    #    v1.9.0: de statusketen heeft géén SOC-poort meer, dus Ontladen mag hier
    #    wel — het RESERVE-SIGNAAL moet off zijn (soc > flor) én mag niet latchen.
    await _zet_daglijst(hass, _daglijst_voortgang(0.30, 0.50, 0.30, 0.10))
    await _trig(hass, 21)
    st = hass.states.get("sensor.shadow_status")
    bs = hass.states.get("binary_sensor.shadow_accu_blokkade")
    assert bs.state == "off", (
        f"SOC 21 > flor 20 → reserve-signaal off (latch aan flor, niet flor+2), got {bs.state}")
    assert st.state == "Ontladen", (
        f"v1.9.0: na curtail, uit boven eis en soc > flor → vers besluit Ontladen, got {st.state}")
    # 3) zelfde situatie (uit wél boven de verkoop-eis) met SOC boven de
    #    band (23 > flor+2): verkoop mag Wél instappen.
    await _zet_daglijst(hass, _daglijst_voortgang(0.30, 0.50, 0.30, 0.10))
    await _trig(hass, 23)
    st = hass.states.get("sensor.shadow_status")
    assert st.state == "Ontladen", f"boven flor+2 mag verkoop wel, got {st.state}"



















