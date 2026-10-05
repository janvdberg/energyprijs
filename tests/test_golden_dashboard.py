"""Golden-dashboard-tests — code en gebruikersdashboard mogen NOOIT meer
uit elkaar lopen (v1.2.41, naar aanleiding van Jans handmatige aanpassing).

tests/golden_dashboard.yaml is exact het dashboard-view zoals Jan het heeft.
Deze tests bewijzen:
  1. cards.py genereert de drie kaarten byte-gelijk aan die golden;
  2. een dashboard dat al aan de golden voldoet wordt NIET herbouwd
     (geen schrijfactie, geen loop bij elke herstart);
  3. een dashboard met de oude v1.2.40-grafiek (twee series, lange titel)
     wordt precies ÉÉN keer vervangen.
"""
import copy
import types
from pathlib import Path
from unittest.mock import patch

import pytest  # noqa: F401  (asyncio via pytest.ini)
import yaml

import custom_components.energyprijs.installer as inst
from homeassistant.components.lovelace.const import LOVELACE_DATA
import homeassistant.components.lovelace.dashboard as lb_dash
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

GOLDEN = yaml.safe_load(
    (Path(__file__).parent / "golden_dashboard.yaml").read_text(encoding="utf-8")
)["views"][0]


# ── 1) golden file == wat cards.py genereert ───────────────────────────────

def test_cards_py_genereert_exact_het_golden_dashboard():
    from custom_components.energyprijs.cards import (ACCUCONTRACT_CARD,
                                                     ACCUEENHEDEN_CARD,
                                                     CONTRACT_CARD,
                                                     GRAFIEK_CARD, NU_CARD,
                                                     PVCONTRACT_CARD,
                                                     PVINSTELLINGEN_CARD)
    g_nu, g_graf, g_contract, g_accuen, g_accuc, g_pv, g_pvinst = GOLDEN["cards"]
    assert NU_CARD == g_nu, "NU_CARD wijkt af van het gebruikersdashboard"
    assert GRAFIEK_CARD == g_graf, "GRAFIEK_CARD wijkt af van het gebruikersdashboard"
    assert CONTRACT_CARD == g_contract, "CONTRACT_CARD wijkt af"
    assert ACCUEENHEDEN_CARD == g_accuen, "ACCUEENHEDEN_CARD wijkt af"
    assert ACCUCONTRACT_CARD == g_accuc, "ACCUCONTRACT_CARD wijkt af"
    assert PVCONTRACT_CARD == g_pv, "PVCONTRACT_CARD wijkt af"
    assert PVINSTELLINGEN_CARD == g_pvinst, "PVINSTELLINGEN_CARD wijkt af"


# ── helper: dashboard-op-schijf nabootsen ──────────────────────────────────

def _fake_lovelace(hass, stored):
    """Patch DashboardsCollection + LovelaceStorage zodat _dashboard_opslaan
    tegen `stored` (de view-dict op schijf) loopt. Geeft de saved-lijst terug.
    In een draaiende HA vult de eerste save de live cache → 2e aanroep 'huidig'.
    """
    saved = []
    # het collectie-item onthoudt zich tussen aanroepen door via een SHARED
    # dict (zoals live-HA): de 2e aanroep vindt het item → 'bijgewerkt', en
    # pas dán is de 'huidig'-uitweg uit de skip-check überhaupt bereikbaar.
    held = {}

    class FakeColl:
        def __init__(self, hass_):
            # copy: de installer mutateert self.data (first["cards"] etc.) —
            # zonder kopie zou hij het gedeelde item mee-beschadigen
            self.data = dict(held)
            self.store = type("S", (), {
                "async_delay_save": lambda self, fn, delay=0: fn()})()
        async def async_load(self): pass
        async def async_create_item(self, item):
            held["x"] = dict(item, id="x"); return held["x"]
        async def async_update_item(self, dash_id, item): pass
        def _data_to_save(self): return list(self.data.values())

    class FakeStore:
        def __init__(self, hass_, entry_): pass
        async def async_load(self, force=False): return copy.deepcopy(stored)
        async def async_save(self, config):
            saved.append(copy.deepcopy(config))
            stored.clear(); stored.update(copy.deepcopy(config))

    class FakeLive:
        _data = None
        async def async_save(self, config): self._data = config

    hass.data[LOVELACE_DATA] = types.SimpleNamespace(
        dashboards={inst.DASH_ID: FakeLive()})
    return saved, (FakeColl, FakeStore)


async def _prep_entry(hass):
    entry = MockConfigEntry(domain="energyprijs", title="Energyprijs")
    entry.add_to_hass(hass)
    ent_reg = er.async_get(hass)
    ent_reg.async_get_or_create("input_number", "energyprijs", "btw",
                                suggested_object_id="prijs_btw")
    hass.states.async_set("sensor.stroomprijs_daglijst", "0.2", {"vandaag": []})
    return entry


# ── 2) golden-dashboard blijft ongemoeid (geen herbouw-loop) ───────────────

async def test_gouden_dashboard_wordt_niet_herbouwd(hass):
    await _prep_entry(hass)
    stored = {"views": [copy.deepcopy(GOLDEN)
                        | {"energyprijs_versie": inst._manifest_version(hass)}]}
    saved, (FakeColl, FakeStore) = _fake_lovelace(hass, stored)
    with patch.object(lb_dash, "LovelaceStorage", FakeStore), \
         patch.object(lb_dash, "DashboardsCollection", FakeColl):
        # 1e aanroep zaait het dashboard-metadata-item (in live-HA bestaat dat
        # al); daarna is de view Golden + gestampt → 'huidig', ZONDER write
        await inst._dashboard_opslaan(hass)
        n_na_zaaien = len(saved)
        res = await inst._dashboard_opslaan(hass)
    assert res.get("act") == "huidig", f"onnodige herbouw: {res}"
    assert len(saved) == n_na_zaaien,         "er is opnieuw weggeschreven terwijl het dashboard al golden was"


# ── 3) oude v1.2.40-grafiek wordt precies één keer vervangen ───────────────

async def test_oude_v1240_grafiek_wordt_precies_een_keer_vervangen(hass):
    await _prep_entry(hass)
    from custom_components.energyprijs.cards import (ACCUCONTRACT_CARD,
                                                     ACCUEENHEDEN_CARD,
                                                     CONTRACT_CARD,
                                                     GRAFIEK_CARD, NU_CARD)
    stale_grafiek = {
        "type": "custom:apexcharts-card",
        "section_mode": True,
        "experimental": {"color_threshold": True,
                         "disable_config_validation": True},
        "graph_span": "24h",
        "span": {"start": "day"},
        "update_interval": "5min",
        "show": {"last_updated": True},
        "now": {"show": True, "label": "nu"},
        "header": {"show": True,
                   "title": "Stroomprijs — bruto · inkoop · verkoop (EUR/kWh)",
                   "show_states": False, "colorize_states": False},
        "series": [copy.deepcopy(GRAFIEK_CARD["series"][0]),
                   {"entity": "sensor.stroomprijs_daglijst",
                    "name": "verkoopprijs", "type": "line",
                    "color": "#d94040", "float_precision": 3,
                    "data_generator": "return [];",
                    "show": {"in_header": False}}],
        "apex_config": {"legend": {"show": False},
                        "xaxis": copy.deepcopy(GRAFIEK_CARD["apex_config"]["xaxis"])},
        "yaxis": copy.deepcopy(GRAFIEK_CARD["yaxis"]),
    }
    stored = {"views": [{"title": "Energie", "path": "energie",
                         "cards": [NU_CARD, stale_grafiek, CONTRACT_CARD],
                         # versie-tag gelíjk aan manifest → alleen de opbouw-check
                         # kan de herbouw nog forcëren (één keer, niet elke ronde)
                         "energyprijs_versie": inst._manifest_version(hass)}]}
    saved, (FakeColl, FakeStore) = _fake_lovelace(hass, stored)
    with patch.object(lb_dash, "LovelaceStorage", FakeStore), \
         patch.object(lb_dash, "DashboardsCollection", FakeColl):
        res1 = await inst._dashboard_opslaan(hass)
        assert res1.get("act") != "huidig", "stale grafiek als actueel herkend"
        new_graf = next(c for c in saved[0]["views"][0]["cards"]
                        if isinstance(c, dict)
                        and c.get("type") == "custom:apexcharts-card")
        assert new_graf == GRAFIEK_CARD
        assert len(new_graf["series"]) == 1
        # accu- en pv-contractkaarten moeten nu ook in de view staan (v1.2.42/v1.3.0)
        kaarten = saved[0]["views"][0]["cards"]
        from custom_components.energyprijs.cards import (PVCONTRACT_CARD,
                                                         PVINSTELLINGEN_CARD)
        assert ACCUEENHEDEN_CARD in kaarten and ACCUCONTRACT_CARD in kaarten
        assert PVCONTRACT_CARD in kaarten and PVINSTELLINGEN_CARD in kaarten
        # tweede aanroep: nu identiek aan golden → huidig, nul extra saves
        res2 = await inst._dashboard_opslaan(hass)
        assert res2.get("act") == "huidig", "tweede ronde bouwde opnieuw"
    assert len(saved) == 1, "meerdere schrijfacties — herbouw-loop"
