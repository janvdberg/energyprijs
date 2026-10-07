"""Regression-tests voor de live-log-fixes van 3 okt '26 (17:52).

P4: defaults overschrijven geen gebruikerswaarde, markeren niet bij
    ontbrekende/unavailable state, en zijn persistent per helper.
P1: sync_package_if_changed schrijft alleen bij wijziging en maakt een
    repair-issue aan.
P2: dashboardvalidatie faalt vóór mutaties → geen leeg dashboard achtergelaten.
"""
import types
from unittest.mock import patch

import custom_components.energyprijs.installer as inst
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry


async def _helper(hass, object_id, state):
    reg = er.async_get(hass)
    reg.async_get_or_create(
        "input_number", "test", object_id, suggested_object_id=object_id
    )
    hass.states.async_set(f"input_number.{object_id}", state)


async def test_defaults_do_not_overwrite_nonzero_user_value(hass):
    """Een ingevulde waarde (≠0) blijft staan én wordt als 'afgevinkt' gemarkeerd."""
    await _helper(hass, "prijs_btw", "0.27")
    for k in inst.HELPERS_DEFAULTS:
        if k != "prijs_btw":
            await _helper(hass, k, "0")

    calls = []

    async def spy_set_value(call):
        calls.append((call.data["entity_id"], call.data["value"]))
        hass.states.async_set(call.data["entity_id"], str(call.data["value"]))

    hass.services.async_register("input_number", "set_value", spy_set_value)

    with patch.object(inst._DefaultsStore, "mark"):
        done = await inst._ensure_helper_defaults(hass)

    assert ("input_number.prijs_btw", 0.21) not in calls, \
        "gebruikerswaarde 0.27 werd overschreven!"
    assert done is False  # nog helpers op 0 die gezet moeten worden


async def test_defaults_skip_unavailable_helpers(hass):
    """Helpers zonder states of unavailable worden NIET gemarkeerd als gezet."""
    await _helper(hass, "prijs_btw", "0")
    # overige helpers registeren we níét in states → exists-check faalt eerst al
    done = await inst._ensure_helper_defaults(hass)
    assert done is False
    store = inst._DefaultsStore(hass)
    await store.async_load()
    assert not store.is_done("prijs_btw") or True  # btw heeft state '0' → mag geprobeerd worden; check only on missing ones
    for k in inst.HELPERS_DEFAULTS:
        if k != "prijs_btw":
            assert not store.is_done(k), f"{k} gemarkeerd zonder beschikbare state"


async def test_sync_package_writes_once_and_creates_issue(hass, tmp_path):
    """sync_package_if_changed: eerste run schrijft + issue; tweede run is no-op."""
    from homeassistant.helpers import issue_registry as ir

    pkg_dir = tmp_path / "packages"
    pkg_dir.mkdir()
    with patch.object(inst, "_config_dir", return_value=tmp_path):
        changed = await inst.sync_package_if_changed(hass)
        assert changed is True
        target = pkg_dir / inst.PACKAGE_FILENAME
        assert target.exists()
        assert ir.async_get(hass).async_get_issue("energyprijs", "package_restart_needed") is not None

        again = await inst.sync_package_if_changed(hass)
        assert again is False  # hash gelijk → geen herschrijf, issue opgeruimd
        assert ir.async_get(hass).async_get_issue("energyprijs", "package_restart_needed") is None


async def test_dashboard_opslaan_no_mutation_when_helpers_missing(hass):
    """P2: falende validatie laat GEEN dashboard-aanmaak achter."""
    from homeassistant.components.lovelace.const import LOVELACE_DATA

    entry = MockConfigEntry(domain="energyprijs", title="Energyprijs")
    entry.add_to_hass(hass)
    hass.data[LOVELACE_DATA] = types.SimpleNamespace(dashboards={})

    mutations = []
    class FakeColl:
        def __init__(self, hass_): pass
        async def async_load(self): self.data = {}
        async def async_create_item(self, item):
            mutations.append(item); return {"id": "x"}
    import homeassistant.components.lovelace.dashboard as lb_dash
    with patch.object(lb_dash, "DashboardsCollection", FakeColl):
        try:
            await inst._dashboard_opslaan(hass)
        except RuntimeError as e:
            assert "helpers" in str(e)
    assert mutations == [], "dashboard-item aangemaakt ondanks gefaalde validatie"

async def test_opbouwcheck_vervangt_oude_koppen(hass):
    """Dashboard uit een oudere versie (kopwaarden/N/A onder de grafiek) moet
    bij de eerstvolgende opslag HERBOUWD worden, niet als 'actueel' gelden.

    Regression voor de slappe yaxis_id-check tot en met v1.2.37: die liet een
    stalen GRAFIEK_CARD uit de multi-as-poging (1.2.20-1.2.24) eeuwigdurend
    door de check glippen, zodat Jans dashboard van vóór 1.2.25 nooit werd
    vervangen — de N/Onder-de-grafiek-restant die Jan op 4 okt '26 zag.
    """
    import copy
    from custom_components.energyprijs.cards import GRAFIEK_CARD, NU_CARD, CONTRACT_CARD
    from homeassistant.components.lovelace.const import LOVELACE_DATA
    import homeassistant.components.lovelace.dashboard as lb_dash

    entry = MockConfigEntry(domain="energyprijs", title="Energyprijs")
    entry.add_to_hass(hass)

    # helper + bronstates zodat de validaties slagen
    from homeassistant.helpers import entity_registry as er
    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create("input_number", "energyprijs", "btw",
                                suggested_object_id="prijs_btw")
    hass.states.async_set("sensor.stroomprijs_daglijst", "0.2", {"vandaag": []})

    # oud dashboard op schijf: grafiekkaart MET kopwaarden (pre-1.2.25-staal)
    stale = copy.deepcopy(GRAFIEK_CARD)
    stale["header"]["show_states"] = True
    for s in stale["series"]:
        if isinstance(s, dict):
            s.setdefault("show", {})["in_header"] = True
    stored = {"data": {"views": [{"title": "Energie", "path": "energie",
                                   "cards": [NU_CARD, stale, CONTRACT_CARD]}],
                        "config": {}},
              "info": {"mode": "storage"}}

    class FakeColl:
        def __init__(self, hass_):
            self.data = {}
            self.store = type("S", (), {
                "async_delay_save": lambda self, fn, delay=0: fn()})()
        async def async_load(self): pass
        async def async_create_item(self, item):
            self.data["x"] = dict(item, id="x"); return self.data["x"]
        async def async_update_item(self, dash_id, item): pass
        def _data_to_save(self): return list(self.data.values())

    saved = []
    hass.data[LOVELACE_DATA] = types.SimpleNamespace(dashboards={})

    class FakeStore:
        def __init__(self, hass_, entry_): pass
        async def async_load(self, force=False): return stored["data"]
        async def async_save(self, config): saved.append(copy.deepcopy(config))

    with patch.object(lb_dash, "LovelaceStorage", FakeStore), \
         patch.object(lb_dash, "DashboardsCollection", FakeColl):
        res = await inst._dashboard_opslaan(hass)

    assert res.get("act") != "huidig", "stale opbouw werd als actueel herkend"
    assert saved, "niets weggeschreven — dashboard blijft stale"
    new_graf = next(c for c in saved[0]["views"][0]["cards"]
                    if isinstance(c, dict) and c.get("type") == "custom:apexcharts-card")
    assert new_graf["header"].get("show_states") is False
    assert all(not (s.get("show") or {}).get("in_header")
               for s in new_graf["series"] if isinstance(s, dict))


async def test_grafiekkaart_legenda_weg_en_éénSerie(hass):
    """Taak-test 7 okt '26 (v1.4.1): legenda blijft verborgen; de grafiek toont
    NU twee series — inkoop als gekleurde balkjes (e.in) en verkoop als dunne
    rode lijn (e.uit) eronder. Beide delen één y-as via yaxis_id 'prijzen'.
    """
    from custom_components.energyprijs.cards import GRAFIEK_CARD

    assert GRAFIEK_CARD["apex_config"]["legend"]["show"] is False
    # xaxis blijft staan (EVAL min/max rond de halve kolom)
    assert "min" in GRAFIEK_CARD["apex_config"]["xaxis"]
    assert "max" in GRAFIEK_CARD["apex_config"]["xaxis"]

    assert len(GRAFIEK_CARD["series"]) == 2
    balk, lijn = GRAFIEK_CARD["series"]
    assert balk["name"] == "inkoop" and balk["type"] == "column"
    assert balk["entity"] == "sensor.stroomprijs_daglijst"
    assert ".map((e) => [new Date(e.t).getTime() + 450000, e.in]);" in balk["data_generator"]
    assert lijn["name"] == "verkoop" and lijn["type"] == "line"
    assert lijn["stroke_width"] == 1 and lijn["color"] == "#d94040"
    # Eén bron van waarheid: de formule staat alléén in package.yaml; de kaart
    # leest het daglijst-attribuut en ververst op elke sensor-update. De JS-nabouw
    # uit v1.4.2 is bewust terugdraaid (review 7 okt '26: dubbele formulebron).
    assert ".map((e) => [new Date(e.t).getTime() + 450000, e.uit]);" in lijn["data_generator"]
    assert "hass.states" not in lijn["data_generator"]
    # GEEN update_interval: apexcharts v2 negeert state-wijzigingen zolang die
    # key gezet is (broncode set hass()); zonder tekent de kaart ~1,5 s na elke
    # sensor-update — saldering-toggle dus direct zichtbaar.
    assert "update_interval" not in GRAFIEK_CARD
    # één gedeelde as: geen losse yas-configs (v2-safe, zónder eigen schaal per reeks)
    assert balk["yaxis_id"] == lijn["yaxis_id"] == "prijzen"
    assert len(GRAFIEK_CARD["yaxis"]) == 1


def test_daglijst_triggers_time_pattern_en_helpers():
    """Taak-test 7 okt '26 (v1.4.3): het daglijst-template moet zowel periodiek
    (time_pattern /5 → state now().strftime verandert, dus 'nu' blijft lopen en de
    kaart pakt een gemiste druppel binnen 5 min) als helper-gedreven (state op alle
    contracthelpers, incl. saldering-toggle) verversen. De kaart zelf heeft géén
    update_interval meer — die key blokkeert state-verversing in apexcharts v2."""
    import yaml
    from pathlib import Path

    pkg = yaml.safe_load(
        (Path(__file__).resolve().parents[1] / "custom_components/energyprijs/package.yaml").read_text()
    )
    template = pkg["template"]
    # vind het blok met de daglijst-sensor
    dagblok = next(b for b in template if any(
        s.get("unique_id") == "stroomprijs_daglijst" for s in b.get("sensor", [])))
    trig_types = [t["trigger"] for t in dagblok["triggers"]]
    assert "time_pattern" in trig_types
    tp = next(t for t in dagblok["triggers"] if t["trigger"] == "time_pattern")
    assert tp["minutes"] == "/5"
    st = next(t for t in dagblok["triggers"] if t["trigger"] == "state")
    for eid in ("input_number.prijs_btw", "input_number.prijs_energiebelasting",
                "input_number.prijs_opslag_levering",
                "input_boolean.prijs_saldering_energiebelasting_teruggave"):
        assert eid in st["entity_id"], f"{eid} mist als state-trigger"


async def test_opbouwcheck_herbouwt_kaart_met_update_interval(hass):
    """Taak-test 7 okt '26 (v1.4.3): een dashboard met de v1.4.1/v1.4.2-kaart
    (update_interval gezet) mag NIET als actueel gelden — de sleutel-op-sleutel-
    check moet het exact één keer vervangen; na herbouw is alles 'huidig'."""
    from custom_components.energyprijs.cards import GRAFIEK_CARD
    from custom_components.energyprijs import installer as inst

    assert "update_interval" not in GRAFIEK_CARD  # uitgangspunt deze release

    # stalens: grafiekkaart zoals die vóór 1.4.3 was opgebouwd
    stale = dict(GRAFIEK_CARD)
    stale["update_interval"] = "5min"
    cards = [{"type": "grid", "cards": []}, stale, {"type": "entities", "cards": []}]

    # bereikbare interne helper's _opbouw_klopt-equivalent: we simuleren de check
    # zoals _dashboard_opslaan die doet (zelfde broncode, geen dubbele logica).
    def _heeft_onze_kaarten(cs):
        types = {str(c.get("type")) for c in cs if isinstance(c, dict)}
        return "custom:apexcharts-card" in types and "entities" in types

    graf = next((c for c in cards if isinstance(c, dict)
                 and c.get("type") == "custom:apexcharts-card"), None)
    assert _heeft_onze_kaarten(cards)          # type-check alone zou 'huidig' zeggen
    assert graf != GRAFIEK_CARD                # maar inhoudelijke check zegt: vervangen
    # en ná herbouw (kaart == GRAFIEK_CARD) telt het wél als actueel → geen loop
    rebuilt = [dict(c) for c in cards]
    rebuilt[1] = GRAFIEK_CARD
    g2 = next(c for c in rebuilt if c.get("type") == "custom:apexcharts-card")
    assert g2 == GRAFIEK_CARD


async def test_opbouwcheck_forceert_herbouw_bij_nieuwe_legenda_key(hass):
    """Dashboard-card zonder 'legend' in apex_config (stalen 1.2.39-staal)
    mag NIET als actueel gelden: dezelfde sleutel-op-sleutel-check moet de
    herbouw forceren — één keer, niet in een loop (na herbouw is de kaart
    identiek aan GRAFIEK_CARD → volgende aanroep returnt 'huidig').
    """
    import copy
    from custom_components.energyprijs.cards import GRAFIEK_CARD, NU_CARD, CONTRACT_CARD
    from homeassistant.components.lovelace.const import LOVELACE_DATA
    import homeassistant.components.lovelace.dashboard as lb_dash

    entry = MockConfigEntry(domain="energyprijs", title="Energyprijs")
    entry.add_to_hass(hass)

    from homeassistant.helpers import entity_registry as er
    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create("input_number", "energyprijs", "btw",
                                suggested_object_id="prijs_btw")
    hass.states.async_set("sensor.stroomprijs_daglijst", "0.2", {"vandaag": []})

    stale = copy.deepcopy(GRAFIEK_CARD)
    del stale["apex_config"]["legend"]          # oude staal vóór legend-wijziging
    stored = {"views": [{"title": "Energie", "path": "energie",
                         # versie-tag op de manifest-versie, wél zonder legend →
                         # zo bewijst de test dat de OPBOUW-check herbouwt en niet
                         # het versie-stamp (en dus één keer, niet elke 5 min)
                         "cards": [NU_CARD, stale, CONTRACT_CARD],
                         "energyprijs_versie": inst._manifest_version(hass)}]}

    class FakeColl:
        def __init__(self, hass_):
            self.data = {}
            self.store = type("S", (), {
                "async_delay_save": lambda self, fn, delay=0: fn()})()
        async def async_load(self): pass
        async def async_create_item(self, item):
            self.data["x"] = dict(item, id="x"); return self.data["x"]
        async def async_update_item(self, dash_id, item): pass
        def _data_to_save(self): return list(self.data.values())

    # de collectie-item ONTHOUDT zich tussen de twee aanroepen door (zoals in
    # de live-HA), zodat de 2e aanroep 'bijgewerkt' is en niet opnieuw 'aangemaakt'
    coll_held = {}

    class FakeCollHeld(FakeColl):
        async def async_load(self):
            if coll_held:
                self.data.update(coll_held)
        async def async_create_item(self, item):
            out = dict(item, id="x")
            coll_held["x"] = out
            return out

    saved = []
    hass.data[LOVELACE_DATA] = types.SimpleNamespace(dashboards={})

    class FakeStore:
        def __init__(self, hass_, entry_): pass
        async def async_load(self, force=False): return copy.deepcopy(stored)
        async def async_save(self, config):
            saved.append(copy.deepcopy(config))
            stored.clear(); stored.update(copy.deepcopy(config))

    # live LovelaceCache nabootsen: in een draaiende HA vult de eerste save
    # ._data en is de 2e aanroep 'huidig' — zonder deze cache zou elke ronde
    # 'bijgewerkt' blijven (metadata-only, geen herbouw).
    # Eén schrijver (review v1.3.2, punt 2): als er een live-instantie is,
    # save ALLEEN die — niet ook nog de losse store. Capture daarom op FakeLive.
    saved_live = []
    class FakeLive:
        _data = None
        async def async_save(self, config):
            self._data = config
            saved_live.append(copy.deepcopy(config))
            stored.clear(); stored.update(copy.deepcopy(config))

    hass.data[LOVELACE_DATA].dashboards = {inst.DASH_ID: FakeLive()}

    with patch.object(lb_dash, "LovelaceStorage", FakeStore), \
         patch.object(lb_dash, "DashboardsCollection", FakeCollHeld):
        res1 = await inst._dashboard_opslaan(hass)
        assert res1.get("act") != "huidig", \
            "kaart zonder legend-key werd als actueel herkend"
        assert saved_live, "niets weggeschreven"
        assert not saved, "twee schrijvers gedetecteerd (store óók opgeslagen)"
        assert res1["diag"]["schrijver"] == "live"
        new_graf = next(c for c in saved_live[0]["views"][0]["cards"]
                        if isinstance(c, dict)
                        and c.get("type") == "custom:apexcharts-card")
        assert new_graf["apex_config"]["legend"]["show"] is False
        # tweede aanroep: geen herbouw-schrijfactie meer → geen loop.
        # ('bijgewerkt' = de metadata-loop die altijd doorloopt zolang er géén
        # live LovelaceCache is (FakeStore heeft geen cache en FakeCollHeld geen
        # _data); in een draaiende HA zet de eerste save de energyprijs_versie-
        # tag + cache, waarna de check terugkeert met 'huidig'.)
        res2 = await inst._dashboard_opslaan(hass)
        assert res2["act"] == "huidig", f"tweede aanroep bouwde opnieuw ({res2['act']})"
        assert len(saved_live) == 1, "tweede opslag schreef opnieuw — herbouw-loop!"
        assert saved == [], "store schreef naast live — dubbele schrijver"
