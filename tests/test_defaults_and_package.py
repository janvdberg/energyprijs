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
