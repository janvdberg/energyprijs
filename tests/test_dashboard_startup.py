"""Test: dashboard wordt aangemaakt bij startup, wachtend op package + HA-started."""
from datetime import timedelta
from unittest.mock import patch

from homeassistant.core import EVENT_HOMEASSISTANT_STARTED
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)


async def test_setup_entry_never_fails(hass):
    """Entry setup mag niet falen, zelfs zonder package en zonder dashboard."""
    from custom_components.energyprijs import async_setup_entry

    entry = MockConfigEntry(domain="energyprijs", title="Energyprijs")
    entry.add_to_hass(hass)
    assert await async_setup_entry(hass, entry) is True


async def test_startup_skips_without_package(hass):
    """Zonder input_number.prijs_btw: _dashboard_opslaan mag NIET worden aangeroepen."""
    from custom_components.energyprijs import async_setup_entry
    import custom_components.energyprijs as cc_pkg

    entry = MockConfigEntry(domain="energyprijs", title="Energyprijs")
    entry.add_to_hass(hass)

    called = []

    async def fake_save(hass_):
        called.append(1)
        return {"act": "aangemaakt"}

    with patch.object(cc_pkg, "_dashboard_opslaan", side_effect=fake_save):
        assert await async_setup_entry(hass, entry) is True
        hass.bus.fire(EVENT_HOMEASSISTANT_STARTED)
        await hass.async_block_till_done()

    assert called == [], "dashboard mocht niet zonder package"


async def test_startup_creates_with_package(hass):
    """Met input_number.prijs_btw + Lovelace actief: _dashboard_opslaan WEL 1x.

    Cold-start-pad: de integratie luistert naar EVENT_HOMEASSISTANT_STARTED, dus
    die fire je vóór async_setup_entry (hass.is_running is in deze harness al True,
    maar het event-coverde pad is wat de productcode bij opstarten bewandelt).
    """
    from homeassistant.components.lovelace.const import LOVELACE_DATA
    from custom_components.energyprijs import async_setup_entry
    import custom_components.energyprijs as cc_pkg

    entry = MockConfigEntry(domain="energyprijs", title="Energyprijs")
    entry.add_to_hass(hass)

    reg = er.async_get(hass)
    reg.async_get_or_create(
        "input_number", "test", "prijs_btw", suggested_object_id="prijs_btw"
    )

    called = []

    async def fake_save(hass_):
        called.append(1)
        return {"act": "aangemaakt"}

    # Lovelace-data exists only when the lovelace component is set up; inject a
    # sentinel so the startup guard passes and the patched save is reached.
    hass.data[LOVELACE_DATA] = object()
    with patch.object(cc_pkg, "_dashboard_opslaan", side_effect=fake_save):
        assert await async_setup_entry(hass, entry) is True
        await hass.async_block_till_done()

    assert len(called) == 1, f"verwacht 1x, kreeg {len(called)}"


async def test_timer_stops_on_version_match(hass):
    """Nadat dashboard_versie == manifest: 5-min timer roept niets meer aan."""
    from custom_components.energyprijs import (
        _manifest_version,
        async_setup_entry,
    )
    import custom_components.energyprijs as cc_pkg

    versie = _manifest_version(hass)

    reg = er.async_get(hass)
    reg.async_get_or_create(
        "input_number", "test", "prijs_btw", suggested_object_id="prijs_btw"
    )

    entry = MockConfigEntry(
        domain="energyprijs",
        title="Energyprijs",
        data={"dashboard_versie": versie},
    )
    entry.add_to_hass(hass)

    called = []

    async def fake_save(hass_):
        called.append(1)
        return {"act": "huidig"}

    with patch.object(cc_pkg, "_dashboard_opslaan", side_effect=fake_save):
        assert await async_setup_entry(hass, entry) is True
        async_fire_time_changed(
            hass, dt_util.utcnow() + timedelta(minutes=5)
        )
        await hass.async_block_till_done()

    assert called == [], f"timer mocht niet roepen bij versie-match, kreeg {len(called)}"
