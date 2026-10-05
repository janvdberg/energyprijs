"""Review 5 okt '26: een verwijderd dashboard MOET terugkomen, ongeacht de marker.

Drie eisen uit de review, één test per eis:
  1. marker == manifestversie maar item ontbreekt op disk → startup/timer bouwt WEL op.
  2. na aanmaken staat DASH_ID in hass.data[LOVELACE_DATA].dashboards (live-registratie,
     probleem 2: websocket vindt anders 'config_not_found' tot een herstart).
  3. bestaand + actueel + live-aanwezig dashboard wordt NIET herbouwd (geen schrijf-loop).
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


class EmptyColl(_CollBase):
    """Disk heeft géén energyprijs-item (dashboard is weggegooid)."""
    def __init__(self, hass_): self.data = {}
    async def async_load(self): pass
    async def async_create_item(self, item):
        out = dict(item, id="x"); self.data["x"] = out; return out


class HeldColl(_CollBase):
    """Disk heeft ons item wél."""
    def __init__(self, hass_):
        self.data = {"e1": {"id": "e1", "url_path": inst.DASH_ID,
                            "mode": "storage", "title": "t", "icon": "i",
                            "show_in_sidebar": True, "require_admin": False}}
    async def async_load(self): pass


async def test_verwijderd_dashboard_wordt_toch_herbouwd_ondanks_correcte_marker(hass):
    """Startup-pad: entry.data/dashboard_versie klopt, item weg → herbouw (pr. 1)."""
    import custom_components.energyprijs as cc_pkg
    from homeassistant.core import EVENT_HOMEASSISTANT_STARTED

    entry = MockConfigEntry(domain="energyprijs", title="Energyprijs",
                            data={"dashboard_versie": inst._manifest_version(hass)})
    entry.add_to_hass(hass)
    _zaai_helpers(hass)
    hass.data[LOVELACE_DATA] = types.SimpleNamespace(dashboards={})

    calls = []
    async def fake_save(hass_):
        calls.append(1)
        return {"act": "aangemaakt"}

    with patch.object(lb_dash, "DashboardsCollection", EmptyColl), \
         patch.object(cc_pkg, "_dashboard_opslaan", side_effect=fake_save), \
         patch.object(cc_pkg, "_ensure_helper_defaults", return_value=True):
        await cc_pkg.async_setup_entry(hass, entry)
        hass.bus.fire(EVENT_HOMEASSISTANT_STARTED)
        await hass.async_block_till_done()

    assert calls == [1], "verwijderd dashboard werd overgeslagen op alleen de marker"
    assert entry.data.get("dashboard_versie") == inst._manifest_version(hass)


async def test_na_aanmaken_staat_dashboard_in_live_data(hass):
    """Probleem 2: LovelaceStorage moet in lov_data.dashboards komen te staan."""
    _zaai_helpers(hass)
    entry = MockConfigEntry(domain="energyprijs", title="Energyprijs")
    entry.add_to_hass(hass)

    lov = types.SimpleNamespace(dashboards={})
    hass.data[LOVELACE_DATA] = lov

    class FakeStoreObj:
        def __init__(self, hass_, entry_): pass
        async def async_load(self, force=False): raise ConfigNotFound
        async def async_save(self, config): pass

    with patch.object(lb_dash, "DashboardsCollection", EmptyColl), \
         patch.object(lb_dash, "LovelaceStorage", FakeStoreObj):
        res = await inst._dashboard_opslaan(hass)

    assert res["act"] == "aangemaakt"
    assert inst.DASH_ID in lov.dashboards, "dashboard niet in live LovelaceData geregistreerd"
    assert res["diag"].get("live_geregistreerd") is True


async def test_actueel_en_live_aanwezig_geen_herbouw_loop(hass):
    """Marker klopt, item bestaat, kaarten actueel, live aanwezig → huidig, 0 saves."""
    from custom_components.energyprijs.cards import (
        ACCUCONTRACT_CARD, ACCUEENHEDEN_CARD, CONTRACT_CARD, GRAFIEK_CARD,
        NU_CARD, PVCONTRACT_CARD, PVINSTELLINGEN_CARD)
    _zaai_helpers(hass)
    entry = MockConfigEntry(domain="energyprijs", title="Energyprijs")
    entry.add_to_hass(hass)

    current = {
        "views": [{
            "title": "Energie", "path": "energie",
            "energyprijs_versie": inst._manifest_version(hass),
            "cards": [NU_CARD, GRAFIEK_CARD, CONTRACT_CARD, ACCUEENHEDEN_CARD,
                      ACCUCONTRACT_CARD, PVCONTRACT_CARD, PVINSTELLINGEN_CARD],
        }],
    }

    saved = []
    class FakeStoreObj:
        def __init__(self, hass_, entry_): pass
        async def async_load(self, force=False): return copy.deepcopy(current)
        async def async_save(self, config): saved.append(config)

    class Live:
        async def async_save(self, config): pass

    lov = types.SimpleNamespace(dashboards={inst.DASH_ID: Live()})
    hass.data[LOVELACE_DATA] = lov

    with patch.object(lb_dash, "DashboardsCollection", HeldColl), \
         patch.object(lb_dash, "LovelaceStorage", FakeStoreObj):
        res = await inst._dashboard_opslaan(hass)

    assert res["act"] == "huidig"
    assert saved == [], "herbouw terwijl alles actueel was — loopgevaar"


async def test_actueel_op_disk_maar_niet_in_liveregistreert_alsnog(hass):
    """Randgeval pr. 2: disk perfect, live mist het item → val door, registreer alsnog."""
    from custom_components.energyprijs.cards import (
        ACCUCONTRACT_CARD, ACCUEENHEDEN_CARD, CONTRACT_CARD, GRAFIEK_CARD,
        NU_CARD, PVCONTRACT_CARD, PVINSTELLINGEN_CARD)
    _zaai_helpers(hass)
    entry = MockConfigEntry(domain="energyprijs", title="Energyprijs")
    entry.add_to_hass(hass)

    current = {
        "views": [{
            "title": "Energie", "path": "energie",
            "energyprijs_versie": inst._manifest_version(hass),
            "cards": [NU_CARD, GRAFIEK_CARD, CONTRACT_CARD, ACCUEENHEDEN_CARD,
                      ACCUCONTRACT_CARD, PVCONTRACT_CARD, PVINSTELLINGEN_CARD],
        }],
    }

    class FakeStoreObj:
        def __init__(self, hass_, entry_): pass
        async def async_load(self, force=False): return copy.deepcopy(current)
        async def async_save(self, config): pass

    lov = types.SimpleNamespace(dashboards={})   # live kent ons item NIET
    hass.data[LOVELACE_DATA] = lov

    with patch.object(lb_dash, "DashboardsCollection", HeldColl), \
         patch.object(lb_dash, "LovelaceStorage", FakeStoreObj):
        res = await inst._dashboard_opslaan(hass)

    # de bestaand-tak registreert live VÓÓR de actueel-check; daarna mag 'huidig'
    assert inst.DASH_ID in lov.dashboards, "geen live-registratie gedaan"
    if "diag" in res:
        assert "repair_issue" not in res["diag"], "ten onrechte repair-issue geplaatst"
