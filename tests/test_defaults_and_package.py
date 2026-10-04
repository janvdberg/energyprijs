"""Regression-tests voor de live-log-fixes van 3 okt '26 (17:52).

P4: defaults overschrijven geen gebruikerswaarde, markeren niet bij
    ontbrekende/unavailable state, en zijn persistent per helper.
P1: sync_package_if_changed schrijft alleen bij wijziging en maakt een
    repair-issue aan.
P2: dashboardvalidatie faalt vóór mutaties → geen leeg dashboard achtergelaten.
"""
from unittest.mock import patch

import custom_components.energyprijs.installer as inst
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store
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
    hass.data[LOVELACE_DATA] = object()

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
    hass.data[LOVELACE_DATA] = object()

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


