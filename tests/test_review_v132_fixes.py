"""Review v1.3.2, punten 1-3: eigen view-behoud, één schrijver, foutafhandeling.

Elke test mapt op een controlepunt uit de review:
  1. Dashboard met een eigen eerste view blijft na herbouw ongewijzigd (view-selectie op path).
  2. Per herbouw precies één schrijfactie (live-instantie wint; store blijft stil).
  3. Blijvende leesfout in dashboard_bestaat() → None → géén herbouw, geen schrijfacties.
"""
import copy
import types
from unittest.mock import patch

from homeassistant.components.lovelace.const import LOVELACE_DATA, ConfigNotFound
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.energyprijs.installer as inst
import homeassistant.components.lovelace.dashboard as lb_dash


def _zaai_helpers(hass):
    from homeassistant.helpers import entity_registry as er
    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create("input_number", "energyprijs", "btw",
                                suggested_object_id="prijs_btw")
    hass.states.async_set("sensor.stroomprijs_daglijst", "0.2", {"vandaag": []})


class _CollBase:
    store = type("S", (), {"async_delay_save": lambda s, fn, delay=0: fn()})()

    def _data_to_save(self):
        return list(self.data.values())


class HeldColl(_CollBase):
    def __init__(self, hass_):
        self.data = {"e1": {"id": "e1", "url_path": inst.DASH_ID,
                            "mode": "storage", "title": "t", "icon": "i",
                            "show_in_sidebar": True, "require_admin": False}}
    async def async_load(self): pass


class BrokenColl(_CollBase):
    """async_load gooit — simuleert een blijvende storage-leesfout."""
    def __init__(self, hass_): self.data = {}
    async def async_load(self): raise OSError("disk eraf")


async def test_eigen_eerste_view_blijft_ongewijzigd(hass):
    """Punt 1: gebruiker heeft een eigen view op positie 0, onze view op 1."""
    from custom_components.energyprijs.cards import GRAFIEK_CARD, NU_CARD
    _zaai_helpers(hass)
    entry = MockConfigEntry(domain="energyprijs", title="Energyprijs")
    entry.add_to_hass(hass)

    eigen = {"title": "Mijn huis", "path": "huis",
             "cards": [{"type": "entities", "entities": ["light.woonkamer"]}]}
    # stale energyprijs-view (oude grafiek → forceert herbouw) op positie 1
    stale = copy.deepcopy(GRAFIEK_CARD)
    del stale["graph_span"]
    ours = {"title": "Energie", "path": "energie",
            "cards": [NU_CARD, stale]}
    current = {"views": [copy.deepcopy(eigen), ours]}

    saved_live = []
    class FakeStoreObj:
        def __init__(self, hass_, entry_): pass
        async def async_load(self, force=False): return copy.deepcopy(current)
        async def async_save(self, config):
            saved_live.append(copy.deepcopy(config))

    class Live:
        async def async_save(self, config): saved_live.append(copy.deepcopy(config))

    lov = types.SimpleNamespace(dashboards={inst.DASH_ID: Live()})
    hass.data[LOVELACE_DATA] = lov

    with patch.object(lb_dash, "DashboardsCollection", HeldColl), \
         patch.object(lb_dash, "LovelaceStorage", FakeStoreObj):
        res = await inst._dashboard_opslaan(hass)

    assert res["act"] != "huidig"
    assert saved_live, "niets herschreven"
    out_views = saved_live[-1]["views"]
    assert len(out_views) == 2, "aantal views veranderd"
    assert out_views[0] == eigen, "eigen eerste view gemuteerd!"
    assert out_views[1]["path"] == "energie"
    graf = next(c for c in out_views[1]["cards"]
                if isinstance(c, dict) and c.get("type") == "custom:apexcharts-card")
    assert graf.get("graph_span"), "onze view niet hersteld"


async def test_legacy_padloze_view_ervt_als_onze(hass):
    """Punt 1-compat: één padloze view (pre-conventie staal van Jan) is van ons."""
    from custom_components.energyprijs.cards import GRAFIEK_CARD
    _zaai_helpers(hass)
    entry = MockConfigEntry(domain="energyprijs", title="Energyprijs")
    entry.add_to_hass(hass)

    stale = copy.deepcopy(GRAFIEK_CARD)
    del stale["graph_span"]
    current = {"views": [{"title": "Energie", "cards": [stale]}]}

    saved_live = []
    class FakeStoreObj:
        def __init__(self, hass_, entry_): pass
        async def async_load(self, force=False): return copy.deepcopy(current)
        async def async_save(self, config): saved_live.append(copy.deepcopy(config))

    class Live:
        async def async_save(self, config): saved_live.append(copy.deepcopy(config))

    lov = types.SimpleNamespace(dashboards={inst.DASH_ID: Live()})
    hass.data[LOVELACE_DATA] = lov

    with patch.object(lb_dash, "DashboardsCollection", HeldColl), \
         patch.object(lb_dash, "LovelaceStorage", FakeStoreObj):
        res = await inst._dashboard_opslaan(hass)

    assert res["act"] != "huidig", "stale legacy-view als actueel herkend"
    assert saved_live
    views = saved_live[-1]["views"]
    assert len(views) == 1, "er is een tweede view bijgekomen — legacy niet geërfd"
    assert views[0]["path"] == inst.VIEW_PATH


async def test_per_herbouw_slechts_een_schrijver(hass):
    """Punt 2: live aanwezig → ALLEEN live slaat op; de losse store blijft stil."""
    _zaai_helpers(hass)
    entry = MockConfigEntry(domain="energyprijs", title="Energyprijs")
    entry.add_to_hass(hass)

    store_saves, live_saves = [], []
    class FakeStoreObj:
        def __init__(self, hass_, entry_): pass
        async def async_load(self, force=False): raise ConfigNotFound
        async def async_save(self, config): store_saves.append(config)

    class Live:
        async def async_save(self, config): live_saves.append(config)

    lov = types.SimpleNamespace(dashboards={inst.DASH_ID: Live()})
    hass.data[LOVELACE_DATA] = lov

    class FreshColl(_CollBase):
        def __init__(self, hass_): self.data = {}
        async def async_load(self): pass
        async def async_create_item(self, item):
            out = dict(item, id="x"); self.data["x"] = out; return out

    with patch.object(lb_dash, "DashboardsCollection", FreshColl), \
         patch.object(lb_dash, "LovelaceStorage", FakeStoreObj):
        res = await inst._dashboard_opslaan(hass)

    assert len(live_saves) == 1, f"verwacht 1 live-save, got {len(live_saves)}"
    assert store_saves == [], "store óók opgeslagen → dubbel lovelace_updated-event"
    assert res["diag"]["schrijver"] == "live"


async def test_blijvende_leesfout_geeft_geen_herbouw(hass):
    """Punt 3: dashboard_bestaat() → None bij exception; aanroeper bouwt NIET op."""
    res = None
    with patch.object(lb_dash, "DashboardsCollection", BrokenColl):
        res = await inst.dashboard_bestaat(hass)
    assert res is None, "leesfout moet None zijn (niet False → anders herbouw-staccato)"


async def test_startup_bouwt_niet_bij_onzekere_check(hass):
    """Punt 3 end-to-end: marker klopt + check gooit → startup overslaat, geen save."""
    import custom_components.energyprijs as cc_pkg
    from homeassistant.core import EVENT_HOMEASSISTANT_STARTED

    entry = MockConfigEntry(domain="energyprijs", title="Energyprijs",
                            data={"dashboard_versie": inst._manifest_version(hass)})
    entry.add_to_hass(hass)
    _zaai_helpers(hass)
    hass.data[LOVELACE_DATA] = types.SimpleNamespace(dashboards={})

    calls = []
    async def fake_save(hass_):
        calls.append(1); return {"act": "aangemaakt"}

    with patch.object(lb_dash, "DashboardsCollection", BrokenColl), \
         patch.object(cc_pkg, "_dashboard_opslaan", side_effect=fake_save), \
         patch.object(cc_pkg, "_ensure_helper_defaults", return_value=True):
        await cc_pkg.async_setup_entry(hass, entry)
        hass.bus.fire(EVENT_HOMEASSISTANT_STARTED)
        await hass.async_block_till_done()

    assert calls == [], "herbouw ondanks onzekere bestaanscheck — loopgevaar bij storage-fout"
